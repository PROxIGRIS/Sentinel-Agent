import sys
from pathlib import Path

def process_file(filepath):
    content = Path(filepath).read_text(encoding="utf-8")
    
    replacements = {
        'print(f"\\n[FATAL] SYSTEM COLLAPSE DETECTED. Transmitting SOS...\\n{crash_log}", file=sys.stderr)': 'logger.error("SYSTEM COLLAPSE DETECTED. Transmitting SOS...", component="system", crash_log=crash_log, exc_info=True)',
        
        'print("[guard] Tactical Monolith Deployed - Input Severed")': 'logger.warning("Tactical Monolith Deployed - Input Severed", component="warden", locked=True)',
        
        'print("[guard] Workstation Unlocked")': 'logger.info("Workstation Unlocked", component="warden")',
        
        'print("[guard] FATAL: Failed to install Win32 hooks.")': 'logger.error("Failed to install Win32 hooks", component="guard", exc_info=True)',
        
        'print(f"[guard] Process terminated: {target_name}")': 'logger.info("Process terminated", component="guard", target_name=target_name)',
        
        'print(f"[guard] terminate_process error: {e}", file=sys.stderr)': 'logger.error("terminate_process error", component="guard", error=str(e), exc_info=True)',
        
        'print(f"[identity] alias read failed: {e}", file=sys.stderr)': 'logger.error("alias read failed", component="identity", error=str(e), exc_info=True)',
        
        'print(f"[priority] elevation failed: {e}", file=sys.stderr)': 'logger.error("elevation failed", component="priority", error=str(e), exc_info=True)',
        
        'print(f"[dom] Context too small or empty (length: {len(dom_text) if dom_text else 0})", file=sys.stderr)': 'logger.error("Context too small or empty", component="dom", length=len(dom_text) if dom_text else 0, exc_info=True)',
        
        'print(f"[dom] Evaluation finished. Score: {score}/{WEB_CRITICAL_THRESHOLD}. Hits: {hits}")': 'logger.info("Evaluation finished", component="dom", score=score, threshold=WEB_CRITICAL_THRESHOLD, hits=hits)',
        
        'print(f"[dom] Score ({score}) did not meet critical threshold ({WEB_CRITICAL_THRESHOLD}).")': 'logger.info("Score did not meet critical threshold", component="dom", score=score, threshold=WEB_CRITICAL_THRESHOLD)',
        
        'print(f"[optics] Uplink established from Chrome Extension.")': 'logger.info("Uplink established from Chrome Extension", component="optics")',
        
        'print(f"[optics] Received DOM chunk: {len(_LATEST_BROWSER_DOM)} chars")': 'logger.info("Received DOM chunk", component="optics", chars=len(_LATEST_BROWSER_DOM))',
        
        'print(f"[optics] Packet parse error: {e}") # Stop swallowing errors': 'logger.error("Packet parse error", component="optics", error=str(e), exc_info=True) # Stop swallowing errors',
        
        'print("[optics] Connection severed by Chrome.")': 'logger.warning("Connection severed by Chrome", component="optics")',
        
        'print("[optics] Starting WebSocket server on 8765...")': 'logger.info("Starting WebSocket server on 8765...", component="optics")',
        
        'print(f"[optics] CRITICAL: Port 8765 is locked! {e}", file=sys.stderr)': 'logger.error("CRITICAL: Port 8765 is locked!", component="optics", error=str(e), exc_info=True)',
        
        'print(f"[optics] Server crashed: {e}", file=sys.stderr)': 'logger.error("Server crashed", component="optics", error=str(e), exc_info=True)',
        
        'print(f"[optics] Event loop fatal: {e}", file=sys.stderr)': 'logger.error("Event loop fatal", component="optics", error=str(e), exc_info=True)',
        
        'print(f"[vault] forensic vault online → {VAULT_DB}")': 'logger.info("forensic vault online", component="vault", vault_db=str(VAULT_DB))',
        
        'print(f"[vault] init failed: {e}", file=sys.stderr)': 'logger.error("Vault init failed", component="vault", error=str(e), exc_info=True)',
        
        'print(f"[vault] cache write failed: {e}", file=sys.stderr)': 'logger.error("cache write failed", component="vault", error=str(e), exc_info=True)',
        
        'print(f"[vault] queued {kind}/{table_name} id={event_id} ts={created_at}")': 'logger.info("queued event", component="vault", kind=kind, table_name=table_name, event_id=event_id, ts=created_at)',
        
        'print(f"[vault] enqueue failed: {e}", file=sys.stderr)': 'logger.error("enqueue failed", component="vault", error=str(e), exc_info=True)',
        
        'print(f"[vault] read failed: {e}", file=sys.stderr)': 'logger.error("read failed", component="vault", error=str(e), exc_info=True)',
        
        'print(f"[vault] delete failed: {e}", file=sys.stderr)': 'logger.error("delete failed", component="vault", error=str(e), exc_info=True)',
        
        'print(f"[storage] created bucket \\\'{EVIDENCE_BUCKET}\\\'")': 'logger.info("created bucket", component="storage", bucket=EVIDENCE_BUCKET)',
        
        'print(f"[storage] bucket bootstrap warning: {e}", file=sys.stderr)': 'logger.warning("bucket bootstrap warning", component="storage", error=str(e))',
        
        'print(f"[identity] read failed: {e}", file=sys.stderr)': 'logger.error("read failed", component="identity", error=str(e), exc_info=True)',
        
        'print(f"[identity] minted hardware uuid → {IDENTITY_FILE}")': 'logger.info("minted hardware uuid", component="identity", identity_file=str(IDENTITY_FILE))',
        
        'print(f"[identity] write failed (using ephemeral id): {e}", file=sys.stderr)': 'logger.error("write failed (using ephemeral id)", component="identity", error=str(e), exc_info=True)',
        
        'print("[identity] Attempting vault handshake with Supabase...")': 'logger.info("Attempting vault handshake with Supabase...", component="identity")',
        
        'print(f"[identity] Reusing existing record for {WORKSTATION_NAME}")': 'logger.info("Reusing existing record", component="identity", workstation_name=WORKSTATION_NAME)',
        
        'print(f"[identity] Handshake secured. Workstation ID: {wid}")': 'logger.info("Handshake secured", component="identity", wid=wid)',
        
        'print("[identity] Network unreachable. Holding boot sequence for 5s...", file=sys.stderr)': 'logger.error("Network unreachable. Holding boot sequence for 5s...", component="identity", exc_info=True)',
        
        'print(f"[identity] Supabase error during handshake: {e}. Retrying...", file=sys.stderr)': 'logger.error("Supabase error during handshake. Retrying...", component="identity", error=str(e), exc_info=True)',
        
        'print(f"[scan] foreground error: {e}", file=sys.stderr)': 'logger.error("foreground error", component="scan", error=str(e), exc_info=True)',
        
        'print(f"[evidence] screenshot failed: {e}", file=sys.stderr)': 'logger.error("screenshot failed", component="evidence", error=str(e), exc_info=True)',
        
        'print("[evidence] Webcam locked by another app or disconnected.", file=sys.stderr)': 'logger.error("Webcam locked by another app or disconnected", component="evidence", exc_info=True)',
        
        'print(f"[evidence] webcam failed: {e}", file=sys.stderr)': 'logger.error("webcam failed", component="evidence", error=str(e), exc_info=True)',
        
        'print(f"[storage] upload {path} attempt {attempt+1} failed: {e}", file=sys.stderr)': 'logger.error("upload failed", component="storage", path=path, attempt=attempt+1, error=str(e), exc_info=True)',
        
        'print(f"[storage] upload {path} exhausted retries — diverting to vault", file=sys.stderr)': 'logger.error("upload exhausted retries — diverting to vault", component="storage", path=path, exc_info=True)',
        
        'print(f"[pipelines] Dossier row reserved id={evidence_row_id}")': 'logger.info("Dossier row reserved", component="pipelines", evidence_row_id=evidence_row_id)',
        
        'print(f"[pipelines] reservation failed: {e}", file=sys.stderr)': 'logger.error("reservation failed", component="pipelines", error=str(e), exc_info=True)',
        
        'print(f"[pipelines] patch failed: {e}", file=sys.stderr)': 'logger.error("patch failed", component="pipelines", error=str(e), exc_info=True)',
        
        'print(f"[pipeline-1] Optics initiated for alert {alert_id}")': 'logger.info("Optics initiated for alert", component="pipeline-1", alert_id=alert_id)',
        
        'print(f"[pipeline-1] Optics secured in {time.time()-t0:.1f}s. screen={bool(screenshot_url)} cam={bool(webcam_url)}")': 'logger.info("Optics secured", component="pipeline-1", duration=time.time()-t0, screen=bool(screenshot_url), cam=bool(webcam_url))',
        
        'print(f"[pipeline-2] Extracting retrospective telemetry lead-up...")': 'logger.info("Extracting retrospective telemetry lead-up...", component="pipeline-2")',
        
        'print(f"[pipeline-2] Lead-up telemetry secured in dossier.")': 'logger.info("Lead-up telemetry secured in dossier.", component="pipeline-2")',
        
        'print(f"[focus] {e}", file=sys.stderr)': 'logger.error("Focus error", component="focus", error=str(e), exc_info=True)',
        
        'print(f"[bypass] Admin bypass activated via {source}. Sentinel reporting suppressed.")': 'logger.warning("Admin bypass activated", component="bypass", source=source)',
        
        'print(f"[bypass] Admin bypass deactivated via {source}. Normal reporting resumed.")': 'logger.info("Admin bypass deactivated", component="bypass", source=source)',
        
        'print(f"[ghost] Panic switch failed to bind: {e}")': 'logger.error("Panic switch failed to bind", component="ghost", error=str(e), exc_info=True)',
        
        'print(f"[guard] Critical violation detected. Workstation locked for admin review.")': 'logger.warning("Critical violation detected. Workstation locked for admin review.", component="guard")',
        
        'print(f"[strike] Critical signal on whitelisted process \\\'{proc}\\\' — freeze suppressed, alert still logged.")': 'logger.warning("Critical signal on whitelisted process — freeze suppressed, alert still logged", component="strike", proc=proc)',
        
        'print(f"[!!!] ALERT [{severity.upper()}] {reason} | {proc} :: {title}")': 'logger.warning("ALERT", component="enforcement", severity=severity.upper(), reason=reason, proc=proc, title=title)',
        
        'print(f"[alerts] live insert failed → vaulting: {e}", file=sys.stderr)': 'logger.error("live insert failed → vaulting", component="alerts", error=str(e), exc_info=True)',
        
        'print(f"[ambient] live insert failed → vaulting: {e}", file=sys.stderr)': 'logger.error("live insert failed → vaulting", component="ambient", error=str(e), exc_info=True)',
        
        'print("[sync] JWT Token likely expired. Reinitializing Supabase client...")': 'logger.info("JWT Token likely expired. Reinitializing Supabase client...", component="sync")',
        
        'print(f"[sync] Client re-init failed: {e}", file=sys.stderr)': 'logger.error("Client re-init failed", component="sync", error=str(e), exc_info=True)',
        
        'print(f"[sync] row #{row_id} exceeded {MAX_VAULT_ATTEMPTS} attempts — dead-lettered and dropped", file=sys.stderr)': 'logger.error("row exceeded max vault attempts — dead-lettered and dropped", component="sync", row_id=row_id, max_attempts=MAX_VAULT_ATTEMPTS, exc_info=True)',
        
        'print(f"[sync] evidence_logs surge non-fatal: {e}", file=sys.stderr)': 'logger.error("evidence_logs surge non-fatal", component="sync", error=str(e), exc_info=True)',
        
        'print(f"[sync] surged row #{row_id} ({table_name}) ts={created_at}")': 'logger.info("surged row", component="sync", row_id=row_id, table_name=table_name, ts=created_at)',
        
        'print(f"[sync] row #{row_id} surge failed (attempt {attempts+1}): {err_msg}", file=sys.stderr)': 'logger.error("row surge failed", component="sync", row_id=row_id, attempt=attempts+1, error=err_msg, exc_info=True)',
        
        'print(f"[sync] daemon armed — probing every {SYNC_INTERVAL}s")': 'logger.info("daemon armed", component="sync", interval=SYNC_INTERVAL)',
        
        'print(f"[sync] {len(pending)} legacy item(s) waiting — link still down")': 'logger.info("legacy item(s) waiting — link still down", component="sync", pending=len(pending))',
        
        'print(f"[sync] connection restored — surging {len(pending)} legacy item(s)")': 'logger.info("connection restored — surging legacy item(s)", component="sync", pending=len(pending))',
        
        'print(f"[sync] surge complete: {wins}/{len(pending)} cleared")': 'logger.info("Surge complete", component="sync", wins=wins, total=len(pending))',
        
        'print(f"[sync] daemon error: {e}", file=sys.stderr)': 'logger.error("daemon error", component="sync", error=str(e), exc_info=True)',
        
        'print("[ocr] No image bytes provided for OCR extraction.", file=sys.stderr)': 'logger.error("No image bytes provided for OCR extraction", component="ocr", exc_info=True)',
        
        'print("[ocr] Starting OCR extraction...", file=sys.stderr)': 'logger.info("Starting OCR extraction...", component="ocr")',
        
        'print("[ocr] OCR timed out after 5s — skipping", file=sys.stderr)': 'logger.error("OCR timed out after 5s — skipping", component="ocr", exc_info=True)',
        
        'print("[ocr] OCR engine returned empty string.", file=sys.stderr)': 'logger.error("OCR engine returned empty string.", component="ocr", exc_info=True)',
        
        'print(f"[ocr] Extraction successful. Suspicion score: {ocr_c_lev}, Hit: \\\'{best_hit}\\\'")': 'logger.info("Extraction successful", component="ocr", suspicion_score=ocr_c_lev, hit=best_hit)',
        
        'print(f"[ocr] OCR analysis failed: {e}", file=sys.stderr)': 'logger.error("OCR analysis failed", component="ocr", error=str(e), exc_info=True)',
        
        'print(f"[significance] Dynamic Incompetence Registry: bypass matched \\\'{proc}\\\' -> 0.0 modifier")': 'logger.info("Dynamic Incompetence Registry: bypass matched", component="significance", proc=proc, modifier=0.0)',
        
        'print("[dom] Active window is a browser, but no DOM context received from websocket telemetry.", file=sys.stderr)': 'logger.error("Active window is a browser, but no DOM context received from websocket telemetry", component="dom", exc_info=True)',
        
        'print(f"[lane-1] Browser detected for \\\'{best_hit}\\\'. Downgrading to Lane 2 for DOM/OCR corroboration.")': 'logger.info("Browser detected. Downgrading to Lane 2 for DOM/OCR corroboration.", component="lane-1", best_hit=best_hit)',
        
        'print(f"[lane-1] Fast-path critical hit \\\'{best_hit}\\\'. Bypassing OCR verification.")': 'logger.info("Fast-path critical hit. Bypassing OCR verification.", component="lane-1", best_hit=best_hit)',
        
        'print(f"[usb-bypass] Faculty USB bypass active. Event downgraded to silent WARNING.")': 'logger.warning("Faculty USB bypass active. Event downgraded to silent WARNING.", component="usb-bypass")',
        
        'print(f"[usb-exec] UNAUTHORIZED USB EXECUTION DETECTED: {proc_str}")': 'logger.warning("UNAUTHORIZED USB EXECUTION DETECTED", component="usb-exec", proc_str=proc_str)',
        
        'print(f"[angel-engine] Semantic intent defused for \\\'{best_hit}\\\'. Suppressing severity multiplier.")': 'logger.info("Semantic intent defused. Suppressing severity multiplier.", component="angel-engine", best_hit=best_hit)',
        
        'print(f"[telemetry] Matrix -> Lev:{c_lev:.2f} | DOM:{c_dom:.2f} | OCR:{c_ocr:.2f} | AppMod:{m_app:.2f} | Final:{s_final:.2f} | Hit:\\\'{best_hit}\\\'")': 'logger.info("Matrix stats", component="telemetry", lev=f"{c_lev:.2f}", dom=f"{c_dom:.2f}", ocr=f"{c_ocr:.2f}", appmod=f"{m_app:.2f}", final=f"{s_final:.2f}", hit=best_hit)',
        
        'print(f"\\n[!!!] ENGINE CRASH DETECTED: {e}\\n", file=sys.stderr)': 'logger.error("ENGINE CRASH DETECTED", component="engine", error=str(e), exc_info=True)',
        
        'print(f"[heartbeat] {e}", file=sys.stderr)': 'logger.error("heartbeat error", component="heartbeat", error=str(e), exc_info=True)',
        
        'print(f"[admin] Controlled shutdown initiated (Action #{action_id})")': 'logger.info("Controlled shutdown initiated", component="admin", action_id=action_id)',
        
        'print(f"[admin] Evidence uploads in progress. System shutdown in {TERMINATE_GRACE_SEC}s.")': 'logger.info("Evidence uploads in progress. System shutdown pending.", component="admin", seconds=TERMINATE_GRACE_SEC)',
        
        'print(f"[admin] Executing command: {cmd.upper()} on {system}")': 'logger.info("Executing command", component="admin", cmd=cmd.upper(), system=system)',
        
        'print(f"[actions] EXPIRED ({age}s old) → {action[\'command\']} #{action[\'id\']}")': 'logger.info("EXPIRED", component="actions", age=age, command=action["command"], action_id=action["id"])',
        
        'print(f"[actions] terminate_process: No target provided in metadata {meta}")': 'logger.warning("terminate_process: No target provided in metadata", component="actions", meta=meta)',
        
        'print(f"[update] Downloading payload from Supabase to replace {current_exe}...")': 'logger.info("Downloading payload from Supabase to replace current executable", component="update", current_exe=current_exe)',
        
        'print(f"[update] SHA-256 verified ✓")': 'logger.info("SHA-256 verified", component="update")',
        
        'print(f"[update] WARNING: no sha256 supplied by admin — proceeding without integrity check", file=sys.stderr)': 'logger.warning("WARNING: no sha256 supplied by admin — proceeding without integrity check", component="update")',
        
        'print(f"[update] OTA Failure: {e}", file=sys.stderr)': 'logger.error("OTA Failure", component="update", error=str(e), exc_info=True)',
        
        'print(f"[identity] Workstation alias updated to: {new_alias}")': 'logger.info("Workstation alias updated", component="identity", new_alias=new_alias)',
        
        'print(f"[identity] Alias forge failed: {e}", file=sys.stderr)': 'logger.error("Alias forge failed", component="identity", error=str(e), exc_info=True)',
        
        'print(f"[identity] Failed to forge alias. Invalid frontend metadata: {meta}", file=sys.stderr)': 'logger.error("Failed to forge alias. Invalid frontend metadata", component="identity", meta=meta, exc_info=True)',
        
        'print(f"[actions] {e}", file=sys.stderr)': 'logger.error("actions error", component="actions", error=str(e), exc_info=True)',
        
        'print("[system] Lazarus Watchdog active. Monitoring vitals...")': 'logger.info("Lazarus Watchdog active. Monitoring vitals...", component="system")',
        
        'print(f"\\n[LAZARUS] {error_msg}")': 'logger.error("LAZARUS error", component="lazarus", error_msg=error_msg, exc_info=True)',
        
        'print("\\n[system] Agent shutting down. Marking workstation offline.")': 'logger.info("Agent shutting down. Marking workstation offline.", component="system")',
        
        'print("[system] Provisioning complete. Agent ready for background execution.")': 'logger.info("Provisioning complete. Agent ready for background execution.", component="system")',
        
        'print("[FATAL] Agent is not provisioned. Run with --provision <URL> <KEY> first.")': 'logger.error("Agent is not provisioned. Run with --provision <URL> <KEY> first.", component="system", exc_info=True)'
    }

    # Handle multi-line one manually
    multiline_old = '''print(f"[update] INTEGRITY FAILURE — hash mismatch. Update aborted. "
                                      f"Expected: {target_sha256} | Got: {file_hash}", file=sys.stderr)'''
    multiline_new = '''logger.error("INTEGRITY FAILURE — hash mismatch. Update aborted.", component="update", expected=target_sha256, got=file_hash, exc_info=True)'''
    
    if multiline_old in content:
        content = content.replace(multiline_old, multiline_new)
        
    for k, v in replacements.items():
        content = content.replace(k, v)

    Path(filepath).write_text(content, encoding="utf-8")

if __name__ == "__main__":
    process_file(r"C:\Sentinel-Agent\Lts\v6.3.5\sentinel_agent.py")
