//! Locating the packaged (or dev-staged) sidecar executable.

use crate::supervisor::SupervisorError;
use std::path::{Path, PathBuf};
use tauri::Manager;

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

pub(crate) fn resolve_sidecar_executable(
    app: &tauri::AppHandle,
) -> Result<PathBuf, SupervisorError> {
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

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn package_candidates_include_nsis_resource_directory() {
        let candidates: Vec<_> = package_local_candidates(Path::new("C:/Review Studio/resources"))
            .map(|path| path.to_string_lossy().to_string())
            .collect();
        assert!(candidates.iter().any(|path| path.contains("_up_")));
    }
}
