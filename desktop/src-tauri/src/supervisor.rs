//! Sidecar process supervision: spawn, health-gate, and tear down the tree.

use crate::health::{probe_health, Health};
use std::path::Path;
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::thread;
use std::time::{Duration, Instant};
use thiserror::Error;

#[cfg(windows)]
use std::os::windows::process::CommandExt;

#[cfg(windows)]
const CREATE_NO_WINDOW: u32 = 0x08000000;

#[derive(Debug, Error)]
pub enum SupervisorError {
    #[error("sidecar is already running")]
    AlreadyRunning,
    #[error("sidecar launch failed: {0}")]
    Launch(#[from] std::io::Error),
    #[error("sidecar did not become healthy")]
    Unhealthy,
    #[error("sidecar executable was not found in the configured or package-local locations")]
    NotFound,
    #[error("sidecar executable path is not valid UTF-8")]
    InvalidPath,
    #[error("could not resolve the packaged sidecar: {0}")]
    Resolve(String),
}

const DEFAULT_HEALTH_URL: &str = "http://127.0.0.1:8765/health";
// Frozen sidecars load large rendering dependencies (PDFium, Pillow,
// matplotlib) on first launch. Five seconds is enough on a warm checkout but
// too short for a clean Windows install, so allow a bounded cold-start window.
const HEALTH_TIMEOUT: Duration = Duration::from_secs(60);

struct SupervisorState {
    child: Option<Child>,
    health: Health,
}

pub struct SidecarSupervisor {
    state: Mutex<SupervisorState>,
    health_url: String,
}

impl Default for SidecarSupervisor {
    fn default() -> Self {
        Self::new(
            std::env::var("DOCS_SIDECAR_HEALTH_URL")
                .unwrap_or_else(|_| DEFAULT_HEALTH_URL.to_owned()),
        )
    }
}

impl SidecarSupervisor {
    pub fn new(health_url: String) -> Self {
        Self {
            state: Mutex::new(SupervisorState {
                child: None,
                health: Health::failed("sidecar is stopped"),
            }),
            health_url,
        }
    }

    pub fn handshake(&self) -> Health {
        self.health()
    }

    pub fn health(&self) -> Health {
        let mut state = self.state.lock().expect("sidecar mutex poisoned");
        if let Some(child) = state.child.as_mut() {
            if child.try_wait().ok().flatten().is_some() {
                state.child = None;
                state.health = Health::failed("sidecar exited before becoming healthy");
            } else if state.health.ready && !probe_health(&self.health_url) {
                state.health = Health::failed("sidecar health endpoint is unavailable");
            }
        }
        state.health.clone()
    }

    pub fn start(&self, executable: &str, workspace: &Path) -> Result<Health, SupervisorError> {
        let mut state = self.state.lock().expect("sidecar mutex poisoned");
        if state.child.is_some() {
            return Err(SupervisorError::AlreadyRunning);
        }
        let executable_path = Path::new(executable);
        let mut command = Command::new(executable_path);
        // Keep the child listener aligned with the supervisor probe. This is
        // required for development/test ports and prevents a configured
        // DOCS_SIDECAR_HEALTH_URL from probing one endpoint while the child
        // silently binds the default 8765 endpoint.
        command
            .arg("--workspace")
            .arg(workspace)
            .arg("--health-url")
            .arg(&self.health_url);
        configure_sidecar_command(&mut command);
        // Keep the console hidden for end users while preserving a durable,
        // local diagnostic stream for startup/runtime failures. The file
        // handle belongs to the child after spawn and is closed with it.
        let log_path = workspace
            .parent()
            .unwrap_or(workspace)
            .join(crate::app_data::SIDECAR_LOG_FILE);
        // The supervisor owns this path; record it separately so a failed
        // packaged startup can be diagnosed even when the UI never loads.
        let _ = std::fs::OpenOptions::new()
            .create(true)
            .append(true)
            .open(&log_path);
        let log = std::fs::OpenOptions::new()
            .create(true)
            .append(true)
            .open(log_path)?;
        let log_stderr = log.try_clone()?;
        let child = command
            .current_dir(executable_path.parent().unwrap_or_else(|| Path::new(".")))
            .stdin(Stdio::null())
            .stdout(Stdio::from(log))
            .stderr(Stdio::from(log_stderr))
            .spawn()?;
        state.child = Some(child);
        state.health = Health::starting();
        drop(state);

        let deadline = Instant::now() + HEALTH_TIMEOUT;
        while Instant::now() < deadline {
            if probe_health(&self.health_url) {
                let mut state = self.state.lock().expect("sidecar mutex poisoned");
                state.health = Health::ready();
                return Ok(state.health.clone());
            }
            thread::sleep(Duration::from_millis(25));
        }

        let mut state = self.state.lock().expect("sidecar mutex poisoned");
        if let Some(mut child) = state.child.take() {
            terminate_process_tree(&mut child);
            let _ = child.wait();
        }
        state.health = Health::failed("sidecar health endpoint timed out");
        Err(SupervisorError::Unhealthy)
    }

    pub fn shutdown(&self) {
        let mut state = self.state.lock().expect("sidecar mutex poisoned");
        if let Some(mut child) = state.child.take() {
            terminate_process_tree(&mut child);
            let _ = child.wait();
        }
        state.health = Health::failed("sidecar is stopped");
    }

    pub(crate) fn fail(&self, error: impl Into<String>) {
        let mut state = self.state.lock().expect("sidecar mutex poisoned");
        state.health = Health::failed(error);
    }
}

fn configure_sidecar_command(command: &mut Command) {
    #[cfg(windows)]
    command.creation_flags(CREATE_NO_WINDOW);
}

fn terminate_process_tree(child: &mut Child) {
    #[cfg(windows)]
    {
        // PyInstaller starts the Python worker as a child of the sidecar. A
        // plain Child::kill only terminates the HTTP parent on Windows and
        // leaves SQLite handles open in the orphaned worker. taskkill /T is
        // the OS-level tree boundary used for clean desktop shutdown.
        let mut command = Command::new("taskkill");
        command.args(["/PID", &child.id().to_string(), "/T", "/F"]);
        command.creation_flags(CREATE_NO_WINDOW);
        let _ = command.output();
    }
    let _ = child.kill();
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn health_is_not_ready_before_sidecar_handshake() {
        let supervisor = SidecarSupervisor::new("http://127.0.0.1:1/health".to_owned());

        let health = supervisor.handshake();

        assert!(!health.ready);
        assert_eq!(health.state, "failed");
        assert_eq!(health.error.as_deref(), Some("sidecar is stopped"));
    }
}
