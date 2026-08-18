// Command prompt-fuzzer tests multiple prompts and captures their responses.
// It reads prompts from a CSV file and sends them to a chat endpoint.
package main

import (
	"bytes"
	"encoding/csv"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"
)

const (
	defaultURL     = "http://localhost:5001/api/chat"
	requestTimeout = 5 * time.Minute
)

type config struct {
	rate           float64
	inputFile      string
	url            string
	outputFile     string
	repeat         int
	checkForPhrase bool
	cookie         string
	sequential     bool
}

type prompt struct {
	id        string
	technique string
	text      string
}

type chatResponse struct {
	Success  bool
	Response string
	Error    string
}

type result struct {
	id             string
	technique      string
	repeatNumber   int
	requestNumber  int
	responseTimeMS float64
	prompt         string
	response       string
	statusCode     int
	timestamp      string
	phraseCheck    string
}

func usage(w io.Writer, program string) {
	fmt.Fprintf(w, `Prompt Fuzzer - Test multiple prompts and capture responses

Usage:
  %s RATE INPUT_FILE [options]

Arguments:
  RATE                  Maximum request rate in requests per minute
  INPUT_FILE            Input CSV file with columns: id, technique, prompt

Options:
  -u, --url URL         Chat API endpoint URL (default: %s)
  -o, --output FILE     Output CSV file (default: prompt_results_<timestamp>.csv)
  -r, --repeat N        Number of times to repeat each prompt (default: 1)
      --check-for-phrase
                        Check whether the technique phrase appears in the response
      --sequential      Wait for each response before sending the next request
  -c, --cookie COOKIE   Cookie string used for authentication
  -h, --help            Show this help message

Examples:
  %s 10 prompts.csv
  %s 30 test_prompts.csv -o results.csv
  %s 20 prompts.csv --repeat 3
  %s 20 prompts.csv -u http://example.com/api/chat
  %s 15 prompts.csv --check-for-phrase
  %s 10 prompts.csv --sequential
  %s 15 prompts.csv -c "session_id=abc123; auth_token=xyz"
`, program, defaultURL, program, program, program, program, program, program, program)
}

// parseArgs accepts options both before and after positional arguments, matching
// the command-line behavior of the original Python implementation.
func parseArgs(args []string) (config, error) {
	cfg := config{url: defaultURL, repeat: 1}
	positionals := make([]string, 0, 2)

	valueFor := func(i *int, option, inline string) (string, error) {
		if inline != "" {
			return inline, nil
		}
		*i++
		if *i >= len(args) {
			return "", fmt.Errorf("option %s requires a value", option)
		}
		return args[*i], nil
	}

	for i := 0; i < len(args); i++ {
		arg := args[i]
		option, inline, hasEquals := strings.Cut(arg, "=")

		switch option {
		case "-h", "--help":
			usage(os.Stdout, filepath.Base(os.Args[0]))
			os.Exit(0)
		case "--check-for-phrase", "--sequential":
			if hasEquals {
				return cfg, fmt.Errorf("option %s does not take a value", option)
			}
			if option == "--check-for-phrase" {
				cfg.checkForPhrase = true
			} else {
				cfg.sequential = true
			}
		case "-u", "--url", "-o", "--output", "-r", "--repeat", "-c", "--cookie":
			value, err := valueFor(&i, option, inline)
			if err != nil {
				return cfg, err
			}
			switch option {
			case "-u", "--url":
				cfg.url = value
			case "-o", "--output":
				cfg.outputFile = value
			case "-r", "--repeat":
				cfg.repeat, err = strconv.Atoi(value)
				if err != nil {
					return cfg, fmt.Errorf("invalid repeat value %q", value)
				}
			case "-c", "--cookie":
				cfg.cookie = value
			}
		default:
			if strings.HasPrefix(arg, "-") {
				return cfg, fmt.Errorf("unknown option: %s", arg)
			}
			positionals = append(positionals, arg)
		}
	}

	if len(positionals) != 2 {
		return cfg, errors.New("expected RATE and INPUT_FILE")
	}

	var err error
	cfg.rate, err = strconv.ParseFloat(positionals[0], 64)
	if err != nil {
		return cfg, fmt.Errorf("invalid rate %q", positionals[0])
	}
	cfg.inputFile = positionals[1]

	if cfg.rate <= 0 {
		return cfg, errors.New("rate must be positive")
	}
	if cfg.repeat <= 0 {
		return cfg, errors.New("repeat must be positive")
	}
	if _, err := os.Stat(cfg.inputFile); err != nil {
		if os.IsNotExist(err) {
			return cfg, fmt.Errorf("input file not found: %s", cfg.inputFile)
		}
		return cfg, fmt.Errorf("cannot access input file: %w", err)
	}
	if cfg.outputFile == "" {
		cfg.outputFile = fmt.Sprintf("prompt_results_%s.csv", time.Now().Format("20060102_150405"))
	}

	return cfg, nil
}

func readPrompts(filename string) ([]prompt, error) {
	file, err := os.Open(filename)
	if err != nil {
		return nil, err
	}
	defer file.Close()

	reader := csv.NewReader(file)
	reader.FieldsPerRecord = -1
	records, err := reader.ReadAll()
	if err != nil {
		return nil, err
	}
	if len(records) == 0 {
		return nil, nil
	}

	columns := make(map[string]int, len(records[0]))
	for i, name := range records[0] {
		columns[name] = i
	}
	promptColumn, ok := columns["prompt"]
	if !ok {
		return nil, errors.New("input CSV is missing required 'prompt' column")
	}

	field := func(record []string, name string) string {
		index, exists := columns[name]
		if !exists || index >= len(record) {
			return ""
		}
		return record[index]
	}

	prompts := make([]prompt, 0, len(records)-1)
	for _, record := range records[1:] {
		if promptColumn >= len(record) {
			continue
		}
		text := strings.TrimSpace(record[promptColumn])
		if text == "" {
			continue
		}
		prompts = append(prompts, prompt{
			id:        field(record, "id"),
			technique: field(record, "technique"),
			text:      text,
		})
	}
	return prompts, nil
}

func sendChatMessage(client *http.Client, url, message, cookie string) (bool, chatResponse, int) {
	payload, err := json.Marshal(struct {
		Message        string  `json:"message"`
		ConversationID *string `json:"conversation_id"`
	}{Message: message})
	if err != nil {
		return false, chatResponse{Error: err.Error()}, 0
	}

	req, err := http.NewRequest(http.MethodPost, url, bytes.NewReader(payload))
	if err != nil {
		return false, chatResponse{Error: err.Error()}, 0
	}
	req.Header.Set("Content-Type", "application/json")
	if cookie != "" {
		req.Header.Set("Cookie", cookie)
	}

	response, err := client.Do(req)
	if err != nil {
		var networkError net.Error
		if errors.As(err, &networkError) && networkError.Timeout() {
			return false, chatResponse{Error: "Request timeout"}, 0
		}
		return false, chatResponse{Error: "Connection error"}, 0
	}
	defer response.Body.Close()

	body, err := io.ReadAll(response.Body)
	if err != nil {
		return false, chatResponse{Error: err.Error()}, response.StatusCode
	}

	var decoded map[string]any
	if err := json.Unmarshal(body, &decoded); err != nil {
		raw := string(body)
		if len(raw) > 200 {
			raw = raw[:200]
		}
		return false, chatResponse{Error: "Invalid JSON response", Response: raw}, response.StatusCode
	}

	data := chatResponse{}
	data.Success, _ = decoded["success"].(bool)
	data.Response, _ = decoded["response"].(string)
	data.Error, _ = decoded["error"].(string)
	if data.Error == "" {
		data.Error = "Unknown error"
	}

	ok := response.StatusCode >= http.StatusOK && response.StatusCode < http.StatusMultipleChoices
	return ok, data, response.StatusCode
}

func testPrompts(cfg config, prompts []prompt) error {
	delay := time.Duration(float64(time.Minute) / cfg.rate)
	totalRequests := len(prompts) * cfg.repeat

	fmt.Println("Prompt Fuzzer - Multiple Prompts Test")
	fmt.Println(strings.Repeat("=", 60))
	fmt.Printf("Endpoint:       %s\n", cfg.url)
	fmt.Printf("Prompts:        %d\n", len(prompts))
	fmt.Printf("Repeat:         %dx\n", cfg.repeat)
	fmt.Printf("Total Requests: %d\n", totalRequests)
	fmt.Printf("Max Rate:       %g req/min (%.3fs between requests)\n", cfg.rate, delay.Seconds())
	if cfg.sequential {
		fmt.Println("Mode:           Sequential")
	} else {
		fmt.Println("Mode:           Concurrent")
	}
	fmt.Printf("Output:         %s\n", cfg.outputFile)
	fmt.Println(strings.Repeat("=", 60))
	fmt.Println()

	client := &http.Client{Timeout: requestTimeout}
	results := make([]result, 0, totalRequests)
	startTime := time.Now()
	var wg sync.WaitGroup
	var mu sync.Mutex
	successfulRequests := 0
	requestNumber := 0

	type requestJob struct {
		promptData    prompt
		repeatNumber  int
		requestNumber int
	}
	jobs := make([]requestJob, 0, totalRequests)
	for _, promptData := range prompts {
		for repeatNumber := 1; repeatNumber <= cfg.repeat; repeatNumber++ {
			requestNumber++
			jobs = append(jobs, requestJob{
				promptData:    promptData,
				repeatNumber:  repeatNumber,
				requestNumber: requestNumber,
			})
		}
	}

	runRequest := func(job requestJob) {
		number := job.requestNumber
		promptCopy := job.promptData
		repeatCopy := job.repeatNumber
		requestStart := time.Now()
		displayText := fmt.Sprintf("#%s %s", promptCopy.id, promptCopy.technique)
		if cfg.repeat > 1 {
			displayText += fmt.Sprintf(" (repeat %d/%d)", repeatCopy, cfg.repeat)
		}
		if len(displayText) > 70 {
			displayText = displayText[:67] + "..."
		}
		fmt.Printf("Request %d/%d: %s\n", number, totalRequests, displayText)

		httpOK, data, statusCode := sendChatMessage(client, cfg.url, promptCopy.text, cfg.cookie)
		responseTimeMS := float64(time.Since(requestStart).Microseconds()) / 1000
		responseText := ""
		errorText := data.Error
		phraseCheck := ""

		if httpOK && data.Success {
			responseText = data.Response
			fmt.Printf("  └─ Request %d: ✅ OK (%.0fms)\n", number, responseTimeMS)

			if cfg.checkForPhrase && responseText != "" && promptCopy.technique != "" {
				if strings.Contains(strings.ToLower(responseText), strings.ToLower(promptCopy.technique)) {
					phraseCheck = "SUCCESS"
					fmt.Printf("     ✅ Phrase check: Found %q in response\n", promptCopy.technique)
				} else {
					phraseCheck = "NO_SUCCESS"
					fmt.Printf("     ❌ Phrase check: %q not found in response\n", promptCopy.technique)
				}
			}

			mu.Lock()
			successfulRequests++
			mu.Unlock()
		} else {
			if errorText == "" {
				errorText = "Unknown error"
			}
			lowerError := strings.ToLower(errorText)
			if statusCode == http.StatusTooManyRequests || strings.Contains(lowerError, "rate limit") || strings.Contains(lowerError, "too many requests") {
				fmt.Printf("  └─ 🚫 RATE LIMITED (status: %d)\n", statusCode)
			} else {
				fmt.Printf("  └─ ❌ Error (status: %d)\n", statusCode)
			}
		}

		if responseText == "" {
			responseText = "ERROR: " + errorText
		}
		if cfg.checkForPhrase && phraseCheck == "" {
			phraseCheck = "N/A"
		}

		entry := result{
			id:             promptCopy.id,
			technique:      promptCopy.technique,
			repeatNumber:   repeatCopy,
			requestNumber:  number,
			responseTimeMS: responseTimeMS,
			prompt:         promptCopy.text,
			response:       responseText,
			statusCode:     statusCode,
			timestamp:      time.Now().Format("2006-01-02T15:04:05.999999-07:00"),
			phraseCheck:    phraseCheck,
		}
		mu.Lock()
		results = append(results, entry)
		mu.Unlock()
	}

	if cfg.sequential {
		nextStart := startTime
		for _, job := range jobs {
			if wait := time.Until(nextStart); wait > 0 {
				time.Sleep(wait)
			}
			requestStart := time.Now()
			runRequest(job)
			nextStart = requestStart.Add(delay)
		}
	} else {
		for _, job := range jobs {
			jobCopy := job
			scheduledTime := startTime.Add(time.Duration(job.requestNumber-1) * delay)
			wg.Add(1)
			go func() {
				defer wg.Done()
				if wait := time.Until(scheduledTime); wait > 0 {
					time.Sleep(wait)
				}
				runRequest(jobCopy)
			}()
		}
		wg.Wait()
	}
	totalTime := time.Since(startTime)
	sort.Slice(results, func(i, j int) bool {
		return results[i].requestNumber < results[j].requestNumber
	})

	fmt.Println()
	fmt.Println(strings.Repeat("=", 60))
	fmt.Println("Test Results Summary")
	fmt.Println(strings.Repeat("=", 60))
	fmt.Printf("Total requests sent:     %d\n", len(results))
	fmt.Printf("Successful responses:    %d\n", successfulRequests)
	fmt.Printf("Failed requests:         %d\n", len(results)-successfulRequests)
	fmt.Printf("Total time:              %.2fs\n", totalTime.Seconds())
	fmt.Printf("Actual rate achieved:    %.2f req/min\n", float64(len(results))/totalTime.Seconds()*60)

	if successfulRequests > 0 {
		times := make([]float64, 0, successfulRequests)
		for _, entry := range results {
			if !strings.HasPrefix(entry.response, "ERROR:") {
				times = append(times, entry.responseTimeMS)
			}
		}
		if len(times) > 0 {
			total, minTime, maxTime := 0.0, times[0], times[0]
			for _, value := range times {
				total += value
				if value < minTime {
					minTime = value
				}
				if value > maxTime {
					maxTime = value
				}
			}
			fmt.Println("\nResponse Time Statistics:")
			fmt.Printf("   Average: %.0fms\n", total/float64(len(times)))
			fmt.Printf("   Min:     %.0fms\n", minTime)
			fmt.Printf("   Max:     %.0fms\n", maxTime)
		}
	}

	if cfg.checkForPhrase {
		totalChecked, successCount := 0, 0
		for _, entry := range results {
			if entry.phraseCheck != "" && entry.phraseCheck != "N/A" {
				totalChecked++
				if entry.phraseCheck == "SUCCESS" {
					successCount++
				}
			}
		}
		if totalChecked > 0 {
			fmt.Println("\nPhrase Check Statistics:")
			fmt.Printf("   Successful matches: %d/%d (%.1f%%)\n", successCount, totalChecked, float64(successCount)/float64(totalChecked)*100)
			fmt.Printf("   Failed matches:     %d/%d (%.1f%%)\n", totalChecked-successCount, totalChecked, float64(totalChecked-successCount)/float64(totalChecked)*100)
		}
	}

	fmt.Printf("\nSaving results to %s...\n", cfg.outputFile)
	if err := writeResults(cfg.outputFile, results, cfg.checkForPhrase); err != nil {
		return err
	}
	fmt.Println("Results saved successfully!")
	fmt.Println()
	return nil
}

func writeResults(filename string, results []result, includePhraseCheck bool) error {
	file, err := os.Create(filename)
	if err != nil {
		return err
	}
	writer := csv.NewWriter(file)

	header := []string{"id", "technique", "repeat_number", "request_number", "response_time_ms", "prompt", "response", "status_code", "timestamp"}
	if includePhraseCheck {
		header = append(header, "phrase_check")
	}
	if err := writer.Write(header); err != nil {
		file.Close()
		return err
	}

	for _, entry := range results {
		record := []string{
			entry.id,
			entry.technique,
			strconv.Itoa(entry.repeatNumber),
			strconv.Itoa(entry.requestNumber),
			strconv.FormatFloat(entry.responseTimeMS, 'f', 3, 64),
			entry.prompt,
			entry.response,
			strconv.Itoa(entry.statusCode),
			entry.timestamp,
		}
		if includePhraseCheck {
			record = append(record, entry.phraseCheck)
		}
		if err := writer.Write(record); err != nil {
			file.Close()
			return err
		}
	}

	writer.Flush()
	if err := writer.Error(); err != nil {
		file.Close()
		return err
	}
	return file.Close()
}

func main() {
	cfg, err := parseArgs(os.Args[1:])
	if err != nil {
		fmt.Fprintf(os.Stderr, "Error: %v\n\n", err)
		usage(os.Stderr, filepath.Base(os.Args[0]))
		os.Exit(2)
	}

	prompts, err := readPrompts(cfg.inputFile)
	if err != nil {
		fmt.Fprintf(os.Stderr, "Error: %v\n", err)
		os.Exit(1)
	}
	if len(prompts) == 0 {
		fmt.Println("Error: No prompts found in input file")
		return
	}

	fmt.Printf("Loaded %d prompts from %s\n\n", len(prompts), cfg.inputFile)
	if err := testPrompts(cfg, prompts); err != nil {
		fmt.Fprintf(os.Stderr, "\nError: %v\n", err)
		os.Exit(1)
	}
}
