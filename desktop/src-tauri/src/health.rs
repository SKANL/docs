//! Sidecar health model and the plain-TCP `/health` probe.

use serde::{Deserialize, Serialize};
use std::io::{Read, Write};
use std::net::{TcpStream, ToSocketAddrs};
use std::time::Duration;

const HEALTH_PROBE_TIMEOUT: Duration = Duration::from_millis(250);
const PROTOCOL: &str = "docs-sidecar/v1";

#[derive(Debug, Clone, Serialize)]
pub struct Health {
    pub ready: bool,
    pub protocol: &'static str,
    pub state: &'static str,
    pub error: Option<String>,
}

impl Health {
    pub(crate) fn starting() -> Self {
        Self {
            ready: false,
            protocol: PROTOCOL,
            state: "starting",
            error: None,
        }
    }

    pub(crate) fn ready() -> Self {
        Self {
            ready: true,
            protocol: PROTOCOL,
            state: "ready",
            error: None,
        }
    }

    pub(crate) fn failed(error: impl Into<String>) -> Self {
        Self {
            ready: false,
            protocol: PROTOCOL,
            state: "failed",
            error: Some(error.into()),
        }
    }
}

#[derive(Deserialize)]
struct SidecarHealthResponse {
    ready: bool,
    protocol: String,
}

pub(crate) fn probe_health(url: &str) -> bool {
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
    status_ok && payload.ready && payload.protocol == PROTOCOL
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::net::TcpListener;
    use std::thread;

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
