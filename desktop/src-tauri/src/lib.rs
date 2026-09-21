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
const HEALTH_PROBE_TIMEOUT: Duration = Duration::from_millis(250);
const DESKTOP_DATA_SCHEMA_VERSION: u32 = 1;

#[derive(Debug, Serialize, Deserialize)]
struct DesktopDataSchema {
    version: u32,
}

fn initialize_app_data(app: &tauri::AppHandle) -> Result<PathBuf, String> {
    let root = app
        .path()
        .app_data_dir()
        .map_err(|error| format!("app data directory: {error}"))?;
    let workspace = root.join("workspace");
    let directories = [
        "documents",
        "templates",
        "assets",
        "runs",
        "artifacts",
        "baselines",
        "passports",
        ".docs",
    ];
    for directory in directories {
        std::fs::create_dir_all(workspace.join(directory))
            .map_err(|error| format!("create workspace/{directory}: {error}"))?;
    }

    let schema_path = workspace.join(".docs").join("desktop-data-schema.json");
    if schema_path.is_file() {
        let existing = std::fs::read(&schema_path)
            .map_err(|error| format!("read desktop data schema: {error}"))?;
        let schema: DesktopDataSchema = serde_json::from_slice(&existing)
            .map_err(|error| format!("parse desktop data schema: {error}"))?;
        if schema.version > DESKTOP_DATA_SCHEMA_VERSION {
            return Err(format!(
                "desktop data schema {} is newer than this application supports ({DESKTOP_DATA_SCHEMA_VERSION})",
                schema.version
            ));
        }
        return Ok(workspace);
    }
    let schema = DesktopDataSchema {
        version: DESKTOP_DATA_SCHEMA_VERSION,
    };
    let encoded = serde_json::to_vec_pretty(&schema)
        .map_err(|error| format!("encode desktop data schema: {error}"))?;
    let temporary = schema_path.with_extension("json.tmp");
    std::fs::write(&temporary, encoded)
        .map_err(|error| format!("write desktop data schema: {error}"))?;
    std::fs::rename(&temporary, &schema_path)
        .map_err(|error| format!("publish desktop data schema: {error}"))?;
    Ok(workspace)
}

fn append_startup_log(app: &tauri::AppHandle, message: &str) {
    let mut paths = vec![std::env::temp_dir().join("docs-desktop-startup.log")];
    if let Ok(root) = app.path().app_data_dir() {
        let _ = std::fs::create_dir_all(&root);
        paths.push(root.join("desktop-startup.log"));
    }
    for path in paths {
        if let Ok(mut file) = std::fs::OpenOptions::new()
            .create(true)
            .append(true)
            .open(path)
        {
            let _ = writeln!(file, "{message}");
        }
    }
}

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
        let log_path = workspace.parent().unwrap_or(workspace).join("sidecar.log");
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
    let parent = resource_dir.parent().unwrap_or(resource_dir);
    sidecar_names().into_iter().flat_map(|name| {
        [
            resource_dir.join("sidecar").join(name),
            resource_dir.join(name),
            // NSIS places bundled resources under `_up_` during a fresh
            // per-user install. Treat that directory as a package resource
            // location, not as a user-controlled workspace path.
            resource_dir.join("_up_").join("sidecar").join(name),
            parent.join("sidecar").join(name),
            parent.join("_up_").join("sidecar").join(name),
        ]
        .into_iter()
    })
}

fn normalize_executable_path(path: PathBuf) -> PathBuf {
    #[cfg(windows)]
    {
        if let Some(value) = path.to_str().and_then(|value| value.strip_prefix(r"\\?\")) {
            return PathBuf::from(value);
        }
    }
    path
}

fn resolve_sidecar_executable(app: &tauri::AppHandle) -> Result<PathBuf, SupervisorError> {
    if let Ok(configured) = std::env::var("DOCS_SIDECAR_EXECUTABLE") {
        let path = PathBuf::from(configured);
        if path.is_file() {
            return Ok(normalize_executable_path(path));
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
    candidate.map(normalize_executable_path)
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
    let workspace = initialize_app_data(&app)?;
    append_startup_log(
        &app,
        &format!(
            "starting sidecar executable={} workspace={}",
            executable,
            workspace.display()
        ),
    );
    supervisor.start(executable, &workspace).map_err(|error| {
        let message = error.to_string();
        supervisor.fail(message.clone());
        message
    })
}

#[tauri::command]
fn sidecar_restart(
    app: tauri::AppHandle,
    supervisor: State<'_, SidecarSupervisor>,
) -> Result<Health, String> {
    supervisor.shutdown();
    sidecar_start(app, supervisor)
}

pub fn run() {
    tauri::Builder::default()
        .plugin(
            tauri_plugin_updater::Builder::new()
                .pubkey("dW50cnVzdGVkIGNvbW1lbnQ6IG1pbmlzaWduIHB1YmxpYyBrZXk6IDFCOTgxRTlGMzdENjkyMzUKUldRMWt0WTNueDZZRzgyY3Bhb3NWWGRMZnF2UmRJOE5sU1pMZnNzdVhJRWsxaVNZVDNRb2hDbkUK")
                .build(),
        )
        .manage(SidecarSupervisor::default())
        .invoke_handler(tauri::generate_handler![
            sidecar_handshake,
            sidecar_health,
            sidecar_start,
            sidecar_restart
        ])
        .setup(|app| {
            initialize_app_data(&app.handle())?;
            append_startup_log(&app.handle(), "desktop setup initialized");
            let handle = app.handle().clone();
            // Do not block Tauri setup on a cold PyInstaller startup. The
            // supervisor owns the readiness state and the UI can observe it
            // through `sidecar/health` while the sidecar warms up.
            let startup_handle = handle.clone();
            std::thread::Builder::new()
                .name("docs-sidecar-startup".to_owned())
                .spawn(move || {
                    let supervisor = startup_handle.state::<SidecarSupervisor>();
                    if let Err(error) = sidecar_start(startup_handle.clone(), supervisor) {
                        append_startup_log(
                            &startup_handle,
                            &format!("sidecar startup failed: {error}"),
                        );
                        eprintln!("sidecar startup failed: {error}");
                    } else {
                        append_startup_log(&startup_handle, "sidecar startup succeeded");
                    }
                })
                .map_err(|error| format!("spawn sidecar startup thread: {error}"))?;
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

    #[test]
    fn desktop_data_schema_is_versioned() {
        let schema = DesktopDataSchema {
            version: DESKTOP_DATA_SCHEMA_VERSION,
        };
        let encoded = serde_json::to_string(&schema).expect("serialize schema");
        assert!(encoded.contains("\"version\":1"));
    }

    #[test]
    fn package_candidates_include_nsis_resource_directory() {
        let candidates: Vec<_> = package_local_candidates(Path::new("C:/Review Studio/resources"))
            .map(|path| path.to_string_lossy().to_string())
            .collect();
        assert!(candidates.iter().any(|path| path.contains("_up_")));
    }
}
