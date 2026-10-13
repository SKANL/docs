mod app_data;
mod health;
mod resolve;
mod supervisor;

use app_data::{append_startup_log, initialize_app_data};
pub use health::Health;
use resolve::resolve_sidecar_executable;
pub use supervisor::{SidecarSupervisor, SupervisorError};
use tauri::{Manager, State};

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
        .inspect_err(|message| supervisor.fail(message.clone()))?;
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
            initialize_app_data(app.handle())?;
            append_startup_log(app.handle(), "desktop setup initialized");
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
