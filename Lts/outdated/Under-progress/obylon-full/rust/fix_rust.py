import re

with open('rust/core/src/main.rs', 'r', encoding='utf-8') as f:
    code = f.read()

# Fix PCWSTR
code = code.replace(
    'windows::core::PCWSTR::from_raw(obylon_common::wide("ui_thread").as_ptr())',
    'windows::core::w!("ui_thread")'
)
code = code.replace(
    'windows::core::PCWSTR::from_raw(obylon_common::wide("process_monitor").as_ptr())',
    'windows::core::w!("process_monitor")'
)
code = code.replace(
    'windows::core::PCWSTR::from_raw(obylon_common::wide("network_monitor").as_ptr())',
    'windows::core::w!("network_monitor")'
)
code = code.replace(
    'windows::core::PCWSTR::from_raw(obylon_common::wide("ipc_server").as_ptr())',
    'windows::core::w!("ipc_server")'
)

# Fix duplicate AtomicU64 / Ordering imports
# At line 42, it says: use std::sync::atomic::{AtomicBool, AtomicU64, AtomicIsize, Ordering};
# Let's just remove AtomicU64 and Ordering from the line 42
code = code.replace(
    'use std::sync::atomic::{AtomicBool, AtomicU64, AtomicIsize, Ordering};',
    'use std::sync::atomic::{AtomicBool, AtomicIsize};'
)

with open('rust/core/src/main.rs', 'w', encoding='utf-8') as f:
    f.write(code)
