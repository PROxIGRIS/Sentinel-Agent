import sys
from pathlib import Path

def process_file(filepath):
    content = Path(filepath).read_text(encoding="utf-8")
    
    replacements = [
        (
            '''print(f"[storage] created bucket '{EVIDENCE_BUCKET}'")''',
            '''logger.info("created bucket", component="storage", bucket=EVIDENCE_BUCKET)'''
        ),
        (
            '''print(f"[strike] Critical signal on whitelisted process '{proc}' — freeze suppressed, alert still logged.")''',
            '''logger.warning("Critical signal on whitelisted process — freeze suppressed, alert still logged", component="strike", proc=proc)'''
        ),
        (
            '''print(f"[ocr] Extraction successful. Suspicion score: {ocr_c_lev}, Hit: '{best_hit}'")''',
            '''logger.info("Extraction successful", component="ocr", suspicion_score=ocr_c_lev, hit=best_hit)'''
        ),
        (
            '''print(f"[significance] Dynamic Incompetence Registry: bypass matched '{proc}' -> 0.0 modifier")''',
            '''logger.info("Dynamic Incompetence Registry: bypass matched", component="significance", proc=proc, modifier=0.0)'''
        ),
        (
            '''print(f"[lane-1] Browser detected for '{best_hit}'. Downgrading to Lane 2 for DOM/OCR corroboration.")''',
            '''logger.info("Browser detected. Downgrading to Lane 2 for DOM/OCR corroboration.", component="lane-1", best_hit=best_hit)'''
        ),
        (
            '''print(f"[lane-1] Fast-path critical hit '{best_hit}'. Bypassing OCR verification.")''',
            '''logger.info("Fast-path critical hit. Bypassing OCR verification.", component="lane-1", best_hit=best_hit)'''
        ),
        (
            '''print(f"[angel-engine] Semantic intent defused for '{best_hit}'. Suppressing severity multiplier.")''',
            '''logger.info("Semantic intent defused. Suppressing severity multiplier.", component="angel-engine", best_hit=best_hit)'''
        ),
        (
            '''print(f"[telemetry] Matrix -> Lev:{c_lev:.2f} | DOM:{c_dom:.2f} | OCR:{c_ocr:.2f} | AppMod:{m_app:.2f} | Final:{s_final:.2f} | Hit:'{best_hit}'")''',
            '''logger.info("Matrix stats", component="telemetry", lev=f"{c_lev:.2f}", dom=f"{c_dom:.2f}", ocr=f"{c_ocr:.2f}", appmod=f"{m_app:.2f}", final=f"{s_final:.2f}", hit=best_hit)'''
        ),
        (
            '''print(f"[update] INTEGRITY FAILURE — hash mismatch. Update aborted. "\n                                      f"Expected: {target_sha256} | Got: {file_hash}", file=sys.stderr)''',
            '''logger.error("INTEGRITY FAILURE — hash mismatch. Update aborted.", component="update", expected=target_sha256, got=file_hash, exc_info=True)'''
        )
    ]
    
    for k, v in replacements:
        if k in content:
            content = content.replace(k, v)
        else:
            print("MISSING:", k)

    Path(filepath).write_text(content, encoding="utf-8")

if __name__ == "__main__":
    process_file(r"C:\Sentinel-Agent\Lts\v6.3.5\sentinel_agent.py")
