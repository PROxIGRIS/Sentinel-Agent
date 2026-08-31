package cmd

// doctor_profile.go: the `obylonc doctor --profile <duration>` implementation.

import (
	"encoding/json"
	"fmt"
	"os"
	"os/signal"
	"sort"
	"strings"
	"time"

	"obylonc/internal/paths"
	"obylonc/internal/platform"
	"obylonc/internal/ui"
)

type perfSnapshot struct {
	Timestamp float64                       `json:"timestamp"`
	Threads   map[string]map[string]float64 `json:"threads"` // OS thread name -> {section name -> cumulative CPU seconds}
}

func loadPerfSnapshot(path string) *perfSnapshot {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil
	}
	var snap perfSnapshot
	if err := json.Unmarshal(data, &snap); err != nil {
		return nil
	}
	return &snap
}

func lookupThreadSections(snap *perfSnapshot, threadName string) map[string]float64 {
	if snap == nil || snap.Threads == nil {
		return nil
	}
	return snap.Threads[threadName]
}

func runDoctorProfile(dur time.Duration) int {
	fmt.Println()
	ui.Step("CPU PROFILE (%s)", formatDuration(dur))
	ui.Muted("Sampling once now, waiting the full duration, sampling once more, then diffing.")
	ui.Muted("obylonc does no work in between — this is a plain sleep, not a poll loop.")
	fmt.Println()

	startWall := time.Now()
	procsA, _ := platform.SnapshotProcesses(doctorProcessNames)
	pyA := loadPerfSnapshot(paths.PerfSnapshotFile())
	coreA := loadPerfSnapshot(paths.CorePerfSnapshotFile())

	if !profileSleep(dur) {
		fmt.Println()
		ui.Warn("Profile canceled.")
		return 1
	}

	endWall := time.Now()
	procsB, _ := platform.SnapshotProcesses(doctorProcessNames)
	pyB := loadPerfSnapshot(paths.PerfSnapshotFile())
	coreB := loadPerfSnapshot(paths.CorePerfSnapshotFile())

	elapsed := endWall.Sub(startWall)

	fmt.Println()
	ui.PrintBanner(fmt.Sprintf("%s PROFILE", strings.ToUpper(formatDuration(elapsed))))

	printProcessProfile("Python Brain", agentExeName, procsA, procsB, pyA, pyB, elapsed)
	printProcessProfile("Rust Core", "ObylonCore.exe", procsA, procsB, coreA, coreB, elapsed)
	printProcessProfile("Rust Broker", "ObylonBroker.exe", procsA, procsB, nil, nil, elapsed)
	printGoCLISelf(startWall, endWall)
	fmt.Println()

	return 0
}

// profileSleep waits for dur, printing a light progress dot every 30s (or
// dur itself, if shorter) so a 20-minute wait doesn't look hung — the dot
// print is the only work done during the wait, everything else is a
// channel select. Returns false if interrupted (Ctrl+C).
func profileSleep(dur time.Duration) bool {
	sigCh := make(chan os.Signal, 1)
	signal.Notify(sigCh, os.Interrupt)
	defer signal.Stop(sigCh)

	done := time.NewTimer(dur)
	defer done.Stop()

	tickEvery := 30 * time.Second
	if dur < tickEvery {
		tickEvery = dur
	}
	var tickCh <-chan time.Time
	if tickEvery > 0 {
		ticker := time.NewTicker(tickEvery)
		defer ticker.Stop()
		tickCh = ticker.C
	}

	printedDots := false
	for {
		select {
		case <-sigCh:
			if printedDots {
				fmt.Println()
			}
			return false
		case <-done.C:
			if printedDots {
				fmt.Println()
			}
			return true
		case <-tickCh:
			fmt.Print(".")
			printedDots = true
		}
	}
}

func formatDuration(d time.Duration) string {
	d = d.Round(time.Second)
	if d < time.Minute {
		return fmt.Sprintf("%ds", int(d.Seconds()))
	}
	return d.String()
}

func cpuDeltaSeconds(before, after uint64) float64 {
	if after < before {
		return 0 // counter reset guard — process restarted mid-window, etc.
	}
	return float64(after-before) / 1e7 // FILETIME units are 100ns
}

func findProcess(samples []platform.ProcessSample, exeName string) platform.ProcessSample {
	for _, s := range samples {
		if strings.EqualFold(s.Name, exeName) {
			return s
		}
	}
	return platform.ProcessSample{Name: exeName}
}

// indexThreadsByName only indexes NAMED threads (SetThreadDescription was
// called). An unnamed thread's CPU time flows into "Unattributed" via the
// process-total-minus-named-threads subtraction below.
func indexThreadsByName(threads []platform.ThreadSample) map[string]platform.ThreadSample {
	out := make(map[string]platform.ThreadSample)
	for _, t := range threads {
		if t.Name == "" {
			continue
		}
		out[t.Name] = t
	}
	return out
}

type profileRow struct {
	name   string
	cpuSec float64
}

// mergeThreadBreakdown returns the row(s) for one OS thread. If the
// app-level JSON has a sub-section breakdown for this exact thread name,
// the thread's single measured delta is REPLACED by its named
// sub-sections plus a "(other)" remainder — never added alongside it,
// which would double-count time already inside the thread's own
// OS-measured total.
func mergeThreadBreakdown(threadName string, threadDeltaSec float64, appA, appB *perfSnapshot) []profileRow {
	sectionsB := lookupThreadSections(appB, threadName)
	if sectionsB == nil {
		return []profileRow{{titleCase(threadName), threadDeltaSec}}
	}
	sectionsA := lookupThreadSections(appA, threadName)

	var out []profileRow
	sectionsTotalSec := 0.0
	for section, cumB := range sectionsB {
		cumA := 0.0
		if sectionsA != nil {
			cumA = sectionsA[section]
		}
		delta := cumB - cumA
		if delta < 0 {
			delta = 0
		}
		sectionsTotalSec += delta
		out = append(out, profileRow{"  " + titleCase(section), delta})
	}

	remainder := threadDeltaSec - sectionsTotalSec
	if remainder > 0.001 {
		out = append(out, profileRow{fmt.Sprintf("  %s (other)", titleCase(threadName)), remainder})
	}
	return out
}

func titleCase(s string) string {
	s = strings.ReplaceAll(s, "_", " ")
	words := strings.Fields(s)
	for i, w := range words {
		if len(w) > 0 {
			words[i] = strings.ToUpper(w[:1]) + w[1:]
		}
	}
	return strings.Join(words, " ")
}

func printProcessProfile(label, exeName string, procsA, procsB []platform.ProcessSample, appA, appB *perfSnapshot, elapsed time.Duration) {
	fmt.Println(ui.Bold(label))
	fmt.Println(strings.Repeat("─", 32))

	a := findProcess(procsA, exeName)
	b := findProcess(procsB, exeName)

	if !b.Found {
		ui.Muted("Not running")
		fmt.Println()
		return
	}
	if !a.Found {
		ui.Muted("Started during the profile window — no baseline yet, try again next cycle")
		fmt.Println()
		return
	}

	elapsedSec := elapsed.Seconds()
	if elapsedSec <= 0 {
		ui.Muted("profile window too short to measure")
		fmt.Println()
		return
	}
	processDeltaSec := cpuDeltaSeconds(a.CPUTime100ns(), b.CPUTime100ns())

	threadsA := indexThreadsByName(a.Threads)
	threadsB := indexThreadsByName(b.Threads)

	var rows []profileRow
	threadTotalSec := 0.0
	for name, tb := range threadsB {
		var threadDeltaSec float64
		if ta, ok := threadsA[name]; ok {
			threadDeltaSec = cpuDeltaSeconds(ta.CPUTime100ns(), tb.CPUTime100ns())
		} else {
			threadDeltaSec = cpuDeltaSeconds(0, tb.CPUTime100ns()) // thread started mid-window
		}
		threadTotalSec += threadDeltaSec
		rows = append(rows, mergeThreadBreakdown(name, threadDeltaSec, appA, appB)...)
	}

	unattributed := processDeltaSec - threadTotalSec
	if unattributed > 0.001 {
		rows = append(rows, profileRow{"Unattributed", unattributed})
	}

	sort.Slice(rows, func(i, j int) bool { return rows[i].cpuSec > rows[j].cpuSec })

	idlePct := 100.0
	for _, r := range rows {
		pct := (r.cpuSec / elapsedSec) * 100.0
		if pct < 0 {
			pct = 0
		}
		idlePct -= pct
		fmt.Printf("  %-28s %6.1f%%\n", r.name, pct)
	}
	if idlePct < 0 {
		idlePct = 0
	}
	fmt.Printf("  %-28s %6.1f%%\n", ui.Dim("Idle"), idlePct)
	fmt.Println()
}

// printGoCLISelf reports obylonc's OWN CPU footprint for this exact
// invocation — a measured number, not a claim, that the profiler
// producing the report above didn't meaningfully load the system while
// doing it.
func printGoCLISelf(start, end time.Time) {
	fmt.Println(ui.Bold("Go CLI (obylonc, this run)"))
	fmt.Println(strings.Repeat("─", 32))

	kernel, user, ok := platform.CurrentProcessCPUTime()
	if !ok {
		ui.Muted("self CPU-time unavailable on this platform")
		fmt.Println()
		return
	}
	elapsedSec := end.Sub(start).Seconds()
	cpuSec := float64(kernel+user) / 1e7
	pct := 0.0
	if elapsedSec > 0 {
		pct = (cpuSec / elapsedSec) * 100.0
	}
	fmt.Printf("  %-28s %6.2f%%   (%.3fs of CPU across the %s wait)\n", "This doctor run", pct, cpuSec, formatDuration(end.Sub(start)))
	fmt.Println()
}
