package paths

import "path/filepath"

// BrokerLogFile is the live log file for ObylonBroker.exe.
func BrokerLogFile() string {
	return filepath.Join(LogDir(), "broker.log")
}

// CoreLogFile is the live log file for ObylonCore.exe.
func CoreLogFile() string {
	return filepath.Join(LogDir(), "core.log")
}
