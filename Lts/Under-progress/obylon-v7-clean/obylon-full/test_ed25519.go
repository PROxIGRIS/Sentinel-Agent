package main
import (
    "fmt"
    "encoding/base64"
    "crypto/ed25519"
)

func main() {
    seedStr := "NJ3Se+OD7ix+jF3oMbtHSqUmKWqU2xDOuodWB4M2YfM="
    seed, _ := base64.StdEncoding.DecodeString(seedStr)
    privKey := ed25519.NewKeyFromSeed(seed)
    
    pubKey := privKey.Public().(ed25519.PublicKey)
    fmt.Printf("Go Public Key: %s\n", base64.StdEncoding.EncodeToString(pubKey))
    
    msg := []byte("{\"license_id\":\"456\",\"node_id\":\"123\",\"hardware_uuid\":\"abc\",\"expires_at\":null,\"issued_at\":\"2026-08-29T00:00:00Z\",\"status\":\"active\"}")
    sig := ed25519.Sign(privKey, msg)
    fmt.Printf("Go Signature: %s\n", base64.StdEncoding.EncodeToString(sig))
    
    pythonSig, _ := base64.StdEncoding.DecodeString("tWQqQNpL+SXk61QYBdu89vhT5dV9etoRJ+3fUvVVkk3exE4bOsjWZVjmJoWGQnp3JZ85rnqQ/K1+KOvMBIk5Bg==")
    
    fmt.Printf("Python Sig Verifies: %v\n", ed25519.Verify(pubKey, msg, pythonSig))
    fmt.Printf("Go Sig Verifies: %v\n", ed25519.Verify(pubKey, msg, sig))
}
