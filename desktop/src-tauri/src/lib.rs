use serde::{Deserialize, Serialize};
use std::io::{Read, Write};
use std::net::{TcpStream, ToSocketAddrs};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::thread;
use std::time::{Duration, Instant};
use tauri::Manager;
use tauri::State;
use thiserror::Error;

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
const HEALTH_TIMEOUT: Duration = Duration::from_secs(5);
const HEALTH_PROBE_TIMEOUT: Duration = Duration::from_millis(250);

struct SupervisorState {
    child: Option<Child>,
    health: Health,
}

pub struct SidecarSupervisor {
    state: Mutex<SupervisorState>,
    health_url: String,
}

#[derive(Debug, Serialize)]
pub struct Health {
    pub ready: bool,
    pub protocol: &'static str,
    pub state: &'static str,
    pub error: Option<String>,
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

    pub fn start(&self, executable: &str) -> Result<Health, SupervisorError> {
        let mut state = self.state.lock().expect("sidecar mutex poisoned");
        if state.child.is_some() {
            return Err(SupervisorError::AlreadyRunning);
        }
        let executable_path = Path::new(executable);
        let child = Command::new(executable_path)
            .current_dir(executable_path.parent().unwrap_or_else(|| Path::new(".")))
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
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
            let _ = child.kill();
            let _ = child.wait();
        }
        state.health = Health::failed("sidecar health endpoint timed out");
        Err(SupervisorError::Unhealthy)
    }

    pub fn shutdown(&self) {
        let mut state = self.state.lock().expect("sidecar mutex poisoned");
        if let Some(mut child) = state.child.take() {
            let _ = child.kill();
            let _ = child.wait();
        }
        state.health = Health::failed("sidecar is stopped");
    }

    fn fail(&self, error: impl Into<String>) {
        let mut state = self.state.lock().expect("sidecar mutex poisoned");
        state.health = Health {
            ready: false,
            protocol: "docs-sidecar/v1",
            state: "failed",
            error: Some(error.into()),
        };
    }
}

impl Clone for Health {
    fn clone(&self) -> Self {
        Self {
            ready: self.ready,
            protocol: self.protocol,
            state: self.state,
            error: self.error.clone(),
        }
    }
}

impl Health {
    fn starting() -> Self {
        Self {
            ready: false,
            protocol: "docs-sidecar/v1",
            state: "starting",
            error: None,
        }
    }

    fn ready() -> Self {
        Self {
            ready: true,
            protocol: "docs-sidecar/v1",
            state: "ready",
            error: None,
        }
    }

    fn failed(error: &'static str) -> Self {
        Self {
            ready: false,
            protocol: "docs-sidecar/v1",
            state: "failed",
            error: Some(error.to_owned()),
        }
    }
}

fn probe_health(url: &str) -> bool {
    let Some(address) = url.strip_prefix("http://") else {
        return false;
    };
    let (host_port, path) = address
        .split_once('/')
        .map_or((address, "/".to_owned()), |(host, path)| {
            (host, format!("/{path}"))
        });
    let Ok(mut addresses) = host_port.to_socket_addrs() else {
        return false;
    };
    let Some(address) = addresses.next() else {
        return false;
    };
    let Ok(mut stream) = TcpStream::connect_timeout(&address, HEALTH_PROBE_TIMEOUT) else {
        return false;
    };
    stream.set_read_timeout(Some(HEALTH_PROBE_TIMEOUT)).ok();
    stream.set_write_timeout(Some(HEALTH_PROBE_TIMEOUT)).ok();
    let request = format!("GET {path} HTTP/1.1\r\nHost: {host_port}\r\nConnection: close\r\n\r\n");
    if stream.write_all(request.as_bytes()).is_err() {
        return false;
    }
    let mut response = String::new();
    if stream.read_to_string(&mut response).is_err() {
        return false;
    }
    let Some((headers, body)) = response.split_once("\r\n\r\n") else {
        return false;
    };
    let status_ok = headers
        .lines()
        .next()
        .and_then(|status| status.split_whitespace().nth(1))
        == Some("200");
    let Ok(payload) = serde_json::from_str::<SidecarHealthResponse>(body) else {
        return false;
    };
    status_ok && payload.ready && payload.protocol == "docs-sidecar/v1"
}

fn sidecar_names() -> [&'static str; 2] {
    if cfg!(windows) {
        ["docs-sidecar.exe", "sidecar.exe"]
    } else {
        ["docs-sidecar", "sidecar"]
    }
}

fn package_local_candidates(resource_dir: &Path) -> impl Iterator<Item = PathBuf> + '_ {
    sidecar_names().into_iter().flat_map(|name| {
        [
            resource_dir.join("sidecar").join(name),
            resource_dir.join(name),
        ]
        .into_iter()
    })
}

fn resolve_sidecar_executable(app: &tauri::AppHandle) -> Result<PathBuf, SupervisorError> {
    if let Ok(configured) = std::env::var("DOCS_SIDECAR_EXECUTABLE") {
        let path = PathBuf::from(configured);
        if path.is_file() {
            return Ok(path);
        }
        return Err(SupervisorError::Resolve(
            "DOCS_SIDECAR_EXECUTABLE does not point to a file".to_owned(),
        ));
    }

    let resource_dir = app
        .path()
        .resource_dir()
        .map_err(|error| SupervisorError::Resolve(error.to_string()))?;
    let candidate = package_local_candidates(&resource_dir)
        .find(|path| path.is_file())
        .or_else(|| {
            // In `tauri dev`, resources are not copied into an app bundle.
            // Resolve the repository-local staged sidecar as a development
            // fallback while keeping packaged installations resource-first.
            let desktop_dir = Path::new(env!("CARGO_MANIFEST_DIR")).parent()?;
            sidecar_names()
                .into_iter()
                .map(|name| desktop_dir.join("sidecar").join(name))
                .find(|path| path.is_file())
        })
        .ok_or(SupervisorError::NotFound);
    candidate
}

#[derive(Deserialize)]
struct SidecarHealthResponse {
    ready: bool,
    protocol: String,
}

#[tauri::command]
fn sidecar_handshake(supervisor: State<'_, SidecarSupervisor>) -> Health {
    supervisor.handshake()
}

#[tauri::command]
fn sidecar_health(supervisor: State<'_, SidecarSupervisor>) -> Health {
    supervisor.health()
}

#[tauri::command]
fn sidecar_start(
    app: tauri::AppHandle,
    supervisor: State<'_, SidecarSupervisor>,
) -> Result<Health, String> {
    let executable = resolve_sidecar_executable(&app).map_err(|error| {
        let message = error.to_string();
        supervisor.fail(message.clone());
        message
    })?;
    let executable = executable
        .to_str()
        .ok_or_else(|| SupervisorError::InvalidPath.to_string())
        .map_err(|message| {
            supervisor.fail(message.clone());
            message
        })?;
    supervisor.start(executable).map_err(|error| {
        let message = error.to_string();
        supervisor.fail(message.clone());
        message
    })
}

pub fn run() {
    tauri::Builder::default()
        .manage(SidecarSupervisor::default())
        .invoke_handler(tauri::generate_handler![
            sidecar_handshake,
            sidecar_health,
            sidecar_start
        ])
        .setup(|app| {
            let handle = app.handle().clone();
            thread::spawn(move || {
                let supervisor = handle.state::<SidecarSupervisor>();
                if let Err(error) = sidecar_start(handle.clone(), supervisor) {
                    eprintln!("sidecar startup failed: {error}");
                }
            });
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building Tauri application")
        .run(|app, event| {
            if let tauri::RunEvent::Exit = event {
                app.state::<SidecarSupervisor>().shutdown();
            }
        });
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::net::TcpListener;

    #[test]
    fn health_is_not_ready_before_sidecar_handshake() {
        let supervisor = SidecarSupervisor::new("http://127.0.0.1:1/health".to_owned());

        let health = supervisor.handshake();

        assert!(!health.ready);
        assert_eq!(health.state, "failed");
        assert_eq!(health.error.as_deref(), Some("sidecar is stopped"));
    }

    #[test]
    fn health_probe_requires_successful_sidecar_response() {
        let listener = TcpListener::bind("127.0.0.1:0").expect("bind test health endpoint");
        let address = listener.local_addr().expect("read test endpoint address");
        let server = thread::spawn(move || {
            let (mut stream, _) = listener.accept().expect("accept health request");
            let mut request = [0; 512];
            let _ = stream.read(&mut request);
            stream
                .write_all(
                    b"HTTP/1.1 200 OK\r\nContent-Length: 48\r\nConnection: close\r\n\r\n{\"ready\":true,\"protocol\":\"docs-sidecar/v1\"}",
                )
                .expect("write health response");
        });

        assert!(probe_health(&format!("http://{address}/health")));
        server.join().expect("join test health endpoint");
    }
}
