package vault

import (
	"os"
	"path/filepath"
	"testing"
)

func TestWriteAtomicallyReplacesOnlyAfterCompleteWrite(t *testing.T) {
	path := filepath.Join(t.TempDir(), "obylon.enc")
	if err := os.WriteFile(path, []byte("old"), 0o600); err != nil {
		t.Fatalf("seed vault: %v", err)
	}

	if err := writeAtomically(path, []byte("new signed vault")); err != nil {
		t.Fatalf("atomic write: %v", err)
	}

	contents, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("read replacement: %v", err)
	}
	if string(contents) != "new signed vault" {
		t.Fatalf("got %q, want complete replacement", contents)
	}

	entries, err := os.ReadDir(filepath.Dir(path))
	if err != nil {
		t.Fatalf("list temporary directory: %v", err)
	}
	for _, entry := range entries {
		if filepath.Ext(entry.Name()) == ".tmp" {
			t.Fatalf("temporary vault file was not cleaned up: %s", entry.Name())
		}
	}
}
