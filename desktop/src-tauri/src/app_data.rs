//! Shell-owned app data: the versioned schema marker and the startup log.

use serde::{Deserialize, Serialize};
use std::io::Write;
use std::path::{Path, PathBuf};
use tauri::Manager;

const DESKTOP_DATA_SCHEMA_VERSION: u32 = 1;

#[derive(Debug, Serialize, Deserialize)]
struct DesktopDataSchema {
    version: u32,
}

pub(crate) fn initialize_app_data(app: &tauri::AppHandle) -> Result<PathBuf, String> {
    let root = app
        .path()
        .app_data_dir()
        .map_err(|error| format!("app data directory: {error}"))?;
    prepare_app_data(&root)
}

/// Prepares the shell-owned app data root and returns the workspace path.
///
/// The workspace directory is deliberately NOT created here: the sidecar's
/// canonical `WorkspaceRegistry.create` writes the marker and layout for a
/// path that does not exist yet, and refuses to adopt an existing directory.
fn prepare_app_data(root: &Path) -> Result<PathBuf, String> {
    std::fs::create_dir_all(root).map_err(|error| format!("create app data root: {error}"))?;
    let workspace = root.join("workspace");

    // Pre-fix installs kept the schema file inside the workspace; honour it.
    let legacy = workspace.join(".docs").join("desktop-data-schema.json");
    if legacy.is_file() {
        check_schema_supported(&legacy)?;
    }
    let schema_path = root.join("desktop-data-schema.json");
    if schema_path.is_file() {
        check_schema_supported(&schema_path)?;
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

fn check_schema_supported(path: &Path) -> Result<(), String> {
    let existing =
        std::fs::read(path).map_err(|error| format!("read desktop data schema: {error}"))?;
    let schema: DesktopDataSchema = serde_json::from_slice(&existing)
        .map_err(|error| format!("parse desktop data schema: {error}"))?;
    if schema.version > DESKTOP_DATA_SCHEMA_VERSION {
        return Err(format!(
            "desktop data schema {} is newer than this application supports ({DESKTOP_DATA_SCHEMA_VERSION})",
            schema.version
        ));
    }
    Ok(())
}

/// File the supervisor points the sidecar's stdout/stderr at, inside the app data root.
pub(crate) const SIDECAR_LOG_FILE: &str = "sidecar.log";

/// Last `max_bytes` of the sidecar log, or "" when there is none. Never fails:
/// the failure screen must still render when the log is missing or unreadable.
pub(crate) fn read_log_tail(root: &Path, max_bytes: usize) -> String {
    let Ok(bytes) = std::fs::read(root.join(SIDECAR_LOG_FILE)) else {
        return String::new();
    };
    let tail = &bytes[bytes.len().saturating_sub(max_bytes)..];
    // Drop a UTF-8 sequence cut in half by the byte window.
    let start = tail
        .iter()
        .take_while(|byte| (**byte & 0xC0) == 0x80)
        .count();
    String::from_utf8_lossy(&tail[start..]).into_owned()
}

pub(crate) fn append_startup_log(app: &tauri::AppHandle, message: &str) {
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

#[cfg(test)]
mod tests {
    use super::*;

    fn unique_root(label: &str) -> PathBuf {
        let root = std::env::temp_dir().join(format!(
            "docs-desktop-{label}-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        let _ = std::fs::remove_dir_all(&root);
        root
    }

    #[test]
    fn prepare_app_data_leaves_the_workspace_for_the_sidecar_to_create() {
        let root = unique_root("fresh");
        let workspace = prepare_app_data(&root).expect("prepare fresh root");
        assert_eq!(workspace, root.join("workspace"));
        assert!(!workspace.exists());
        assert!(root.join("desktop-data-schema.json").is_file());
        let _ = std::fs::remove_dir_all(&root);
    }

    #[test]
    fn prepare_app_data_refuses_a_newer_legacy_schema() {
        let root = unique_root("legacy");
        let docs = root.join("workspace").join(".docs");
        std::fs::create_dir_all(&docs).unwrap();
        std::fs::write(docs.join("desktop-data-schema.json"), br#"{"version": 99}"#).unwrap();
        let error = prepare_app_data(&root).expect_err("newer legacy schema");
        assert!(error.contains("newer"));
        let _ = std::fs::remove_dir_all(&root);
    }

    #[test]
    fn prepare_app_data_refuses_a_newer_root_schema() {
        let root = unique_root("root");
        std::fs::create_dir_all(&root).unwrap();
        std::fs::write(root.join("desktop-data-schema.json"), br#"{"version": 99}"#).unwrap();
        let error = prepare_app_data(&root).expect_err("newer root schema");
        assert!(error.contains("newer"));
        let _ = std::fs::remove_dir_all(&root);
    }

    #[test]
    fn read_log_tail_returns_only_the_last_bytes_on_a_char_boundary() {
        let root = unique_root("log");
        std::fs::create_dir_all(&root).unwrap();
        let log = root.join(SIDECAR_LOG_FILE);
        std::fs::write(
            &log,
            "línea uno
línea dos
línea tres
",
        )
        .unwrap();
        let tail = read_log_tail(&root, 14);
        assert!(tail.ends_with(
            "línea tres
"
        ));
        assert!(!tail.contains("uno"));
        assert_eq!(
            read_log_tail(&root, 10_000),
            "línea uno
línea dos
línea tres
"
        );
        let _ = std::fs::remove_dir_all(&root);
    }

    #[test]
    fn read_log_tail_is_empty_when_there_is_no_log() {
        let root = unique_root("nolog");
        assert_eq!(read_log_tail(&root, 100), "");
    }

    #[test]
    fn desktop_data_schema_is_versioned() {
        let schema = DesktopDataSchema {
            version: DESKTOP_DATA_SCHEMA_VERSION,
        };
        let encoded = serde_json::to_string(&schema).expect("serialize schema");
        assert!(encoded.contains("\"version\":1"));
    }
}
