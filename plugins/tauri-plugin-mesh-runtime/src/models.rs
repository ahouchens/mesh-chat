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

#[derive(Debug, Default, Deserialize)]
pub struct NativeResponse {
    pub json: String,
}
