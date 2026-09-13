package cmd

import "testing"

func TestTranslateRustBrokerEvent(t *testing.T) {
	e, ok := translateLogLine("Broker", "[1789297200.123] INFO [broker] core spawned into interactive session session_id=1 pid=42 token_kind=wts-user")
	if !ok {
		t.Fatal("expected rust log line to parse")
	}
	if e.Code != "OBY-BOOT-CORE-START" || e.Fields["pid"] != "42" {
		t.Fatalf("unexpected event: %#v", e)
	}
	if e.Message != "Broker launched Obylon Core (PID 42)." {
		t.Fatalf("unexpected humanized message: %q", e.Message)
	}
}

func TestTranslateBrainEvent(t *testing.T) {
	e, ok := translateLogLine("Brain", "[12:34:56.123456] ✖ [license] Activation failed error=unavailable")
	if !ok {
		t.Fatal("expected brain log line to parse")
	}
	if e.Level != "ERROR" || e.Component != "license" || e.Fields["error"] != "unavailable" {
		t.Fatalf("unexpected event: %#v", e)
	}
}

func TestDecodeWindowsExitCodes(t *testing.T) {
	cases := map[string]string{
		"0xC0000135": "OBY-WIN-DLL-MISSING",
		"3221225781": "OBY-WIN-DLL-MISSING",
		"0xC000007B": "OBY-WIN-BAD-IMAGE",
		"78":         "OBY-SECURITY-HOLD",
	}
	for raw, want := range cases {
		got, ok := decodeWindowsExitCode(raw)
		if !ok || got.code != want {
			t.Fatalf("%s: got %#v ok=%v, want %s", raw, got, ok, want)
		}
	}
}
