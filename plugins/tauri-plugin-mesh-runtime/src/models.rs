use serde::{Deserialize, Serialize};
use serde_json::Value;

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct InitializeRequest {
    pub display_name: Option<String>,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct CommandRequest {
    pub command: String,
    pub payload: Value,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ThemeRequest {
    pub theme: String,
}

#[derive(Debug, Serialize)]
pub struct ExternalLinkRequest {
    pub url: String,
}

#[derive(Debug, Serialize)]
pub struct DirectExchangeRequest {
    pub json: String,
}

#[derive(Debug, Serialize)]
pub struct BackgroundAvailabilityRequest {
    pub enabled: bool,
}

#[derive(Debug, Serialize)]
pub struct CallMediaRequest {
    pub media: String,
}

#[derive(Debug, Default, Deserialize)]
pub struct NativeResponse {
    pub json: String,
}
