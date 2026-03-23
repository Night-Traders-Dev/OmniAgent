#[tauri::command]
fn get_server_url() -> String {
    std::env::var("OMNIAGENT_URL").unwrap_or_else(|_| "http://localhost:8000".to_string())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![get_server_url])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
