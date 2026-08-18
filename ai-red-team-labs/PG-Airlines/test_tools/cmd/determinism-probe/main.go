// Command determinism-probe tests a chat endpoint for response determinism and rate
// limiting by sending the same message repeatedly.
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
	"sync/atomic"
	"time"
	"unicode"
)

const defaultURL = "http://localhost:5001/api/chat"

type config struct {
	message     string
	numRequests int
	rate        float64
	url         string
	outputFile  string
	concurrent  bool
}

type chatData struct {
	success         bool
	response        string
	responsePresent bool
	errorText       string
	conversationID  string
}

type probeResult struct {
	requestNumber  int
	timestamp      string
	statusCode     int
	success        bool
	responseText   string
	errorText      string
	responseTime   time.Duration
	conversationID string
}

type responseStats struct {
	n             int
	averageTokens float64
	medianTokens  float64
	minimumTokens int
	maximumTokens int
}

type rateLimitInfo struct {
	requestNumber int
	threshold     float64
	statusCode    int
	errorText     string
	elapsedTime   time.Duration
}

func usage(w io.Writer, program string) {
	fmt.Fprintf(w, `Determinism Probe - Test a chat endpoint for determinism and rate limiting

Usage:
  %s MESSAGE NUM_REQUESTS RATE [options]

Arguments:
  MESSAGE              Message to send to the chat endpoint
  NUM_REQUESTS         Number of times to send the message
  RATE                 Request rate in requests per minute

Options:
  -u, --url URL        Chat API endpoint URL (default: %s)
  -o, --output FILE    Output CSV file (default: probe_results_<mode>_<timestamp>.csv)
  -c, --concurrent     Send at the specified rate regardless of response time
  -h, --help           Show this help message

Examples:
  %s "Explain the principle of least privilege in one sentence." 10 5
  %s "Return exactly the word READY." 50 120 --concurrent -o results.csv
  %s "List three benefits of unit testing." 20 10 -u http://localhost:5001/api/chat
`, program, defaultURL, program, program, program)
}

// parseArgs accepts options before or after positional arguments.
func parseArgs(args []string) (config, error) {
	cfg := config{url: defaultURL}
	positionals := make([]string, 0, 3)
	optionsEnded := false

	valueFor := func(index *int, option, inline string, hasEquals bool) (string, error) {
		if hasEquals {
			return inline, nil
		}
		(*index)++
		if *index >= len(args) {
			return "", fmt.Errorf("option %s requires a value", option)
		}
		return args[*index], nil
	}

	for index := 0; index < len(args); index++ {
		arg := args[index]
		if optionsEnded {
			positionals = append(positionals, arg)
			continue
		}
		if arg == "--" {
			optionsEnded = true
			continue
		}

		option, inline, hasEquals := strings.Cut(arg, "=")
		switch option {
		case "-h", "--help":
			usage(os.Stdout, filepath.Base(os.Args[0]))
			os.Exit(0)
		case "-c", "--concurrent":
			if hasEquals {
				return cfg, errors.New("option --concurrent does not take a value")
			}
			cfg.concurrent = true
		case "-u", "--url", "-o", "--output":
			value, err := valueFor(&index, option, inline, hasEquals)
			if err != nil {
				return cfg, err
			}
			switch option {
			case "-u", "--url":
				cfg.url = value
			case "-o", "--output":
				cfg.outputFile = value
			}
		default:
			if strings.HasPrefix(arg, "-") {
				return cfg, fmt.Errorf("unknown option: %s", arg)
			}
			positionals = append(positionals, arg)
		}
	}

	if len(positionals) != 3 {
		return cfg, errors.New("expected MESSAGE, NUM_REQUESTS, and RATE")
	}
	cfg.message = positionals[0]

	var err error
	cfg.numRequests, err = strconv.Atoi(positionals[1])
	if err != nil {
		return cfg, fmt.Errorf("invalid num_requests value %q", positionals[1])
	}
	cfg.rate, err = strconv.ParseFloat(positionals[2], 64)
	if err != nil {
		return cfg, fmt.Errorf("invalid rate value %q", positionals[2])
	}
	if cfg.numRequests <= 0 {
		return cfg, errors.New("num_requests must be positive")
	}
	if cfg.rate <= 0 {
		return cfg, errors.New("rate must be positive")
	}
	if cfg.outputFile == "" {
		mode := "sequential"
		if cfg.concurrent {
			mode = "concurrent"
		}
		cfg.outputFile = fmt.Sprintf("probe_results_%s_%s.csv", mode, time.Now().Format("20060102_150405"))
	}
	return cfg, nil
}

func calculateDelay(requestsPerMinute float64) (time.Duration, error) {
	if requestsPerMinute <= 0 {
		return 0, errors.New("requests per minute must be positive")
	}
	return time.Duration(float64(time.Minute) / requestsPerMinute), nil
}

func stringifyJSON(value any) string {
	switch typed := value.(type) {
	case nil:
		return ""
	case string:
		return typed
	case json.Number:
		return typed.String()
	default:
		return fmt.Sprint(typed)
	}
}

func sendChatMessage(client *http.Client, url, message string) (bool, chatData, int) {
	payload, err := json.Marshal(struct {
		Message        string  `json:"message"`
		ConversationID *string `json:"conversation_id"`
	}{Message: message})
	if err != nil {
		return false, chatData{errorText: err.Error()}, 0
	}

	request, err := http.NewRequest(http.MethodPost, url, bytes.NewReader(payload))
	if err != nil {
		return false, chatData{errorText: err.Error()}, 0
	}
	request.Header.Set("Content-Type", "application/json")

	response, err := client.Do(request)
	if err != nil {
		var networkError net.Error
		if errors.As(err, &networkError) && networkError.Timeout() {
			return false, chatData{errorText: "Request timeout"}, 0
		}
		return false, chatData{errorText: "Connection error"}, 0
	}
	defer response.Body.Close()

	body, err := io.ReadAll(response.Body)
	if err != nil {
		return false, chatData{errorText: err.Error()}, response.StatusCode
	}

	var decoded map[string]any
	decoder := json.NewDecoder(bytes.NewReader(body))
	decoder.UseNumber()
	if err := decoder.Decode(&decoded); err != nil {
		return response.StatusCode >= 200 && response.StatusCode < 300, chatData{errorText: "Invalid JSON response"}, response.StatusCode
	}

	data := chatData{}
	data.success, _ = decoded["success"].(bool)
	if value, exists := decoded["response"]; exists {
		data.responsePresent = true
		data.response = stringifyJSON(value)
	}
	if value, exists := decoded["error"]; exists {
		data.errorText = stringifyJSON(value)
	}
	if value, exists := decoded["conversation_id"]; exists {
		data.conversationID = stringifyJSON(value)
	}

	httpSuccess := response.StatusCode >= http.StatusOK && response.StatusCode < http.StatusMultipleChoices
	return httpSuccess, data, response.StatusCode
}

func isRateLimit(statusCode int, errorText string) bool {
	lowerError := strings.ToLower(errorText)
	return statusCode == http.StatusTooManyRequests ||
		strings.Contains(lowerError, "rate limit") ||
		strings.Contains(lowerError, "too many requests")
}

func timestampNow() string {
	return time.Now().Format("2006-01-02T15:04:05.000000")
}

// tokenCount matches Python's Unicode-oriented word-or-punctuation tokenization:
// adjacent letters/numbers/underscores form one token and every other non-space
// rune forms its own token.
func tokenCount(value string) int {
	count := 0
	inWord := false
	for _, character := range value {
		isWord := unicode.IsLetter(character) || unicode.IsNumber(character) || character == '_'
		if isWord {
			if !inWord {
				count++
			}
			inWord = true
			continue
		}
		inWord = false
		if !unicode.IsSpace(character) {
			count++
		}
	}
	return count
}

func basicStats(batch []string) responseStats {
	if len(batch) == 0 {
		return responseStats{}
	}
	lengths := make([]int, len(batch))
	total := 0
	for index, value := range batch {
		lengths[index] = tokenCount(value)
		total += lengths[index]
	}
	sort.Ints(lengths)
	median := float64(lengths[len(lengths)/2])
	if len(lengths)%2 == 0 {
		median = float64(lengths[len(lengths)/2-1]+lengths[len(lengths)/2]) / 2
	}
	return responseStats{
		n:             len(batch),
		averageTokens: float64(total) / float64(len(lengths)),
		medianTokens:  median,
		minimumTokens: lengths[0],
		maximumTokens: lengths[len(lengths)-1],
	}
}

func analyzeAndPrint(results []probeResult, successfulRequests int) {
	if successfulRequests > 1 {
		unique := make(map[string]struct{})
		for _, result := range results {
			if result.responseText != "" {
				unique[result.responseText] = struct{}{}
			}
		}
		uniqueResponses := len(unique)
		fmt.Println("\nDeterminism Analysis:")
		fmt.Printf("   Unique responses:      %d/%d\n", uniqueResponses, successfulRequests)
		switch {
		case uniqueResponses == 1:
			fmt.Println("   Fully deterministic (all responses identical)")
		case uniqueResponses == successfulRequests:
			fmt.Println("   Non-deterministic (all responses different)")
		default:
			fmt.Printf("   Partially deterministic (%d variations)\n", uniqueResponses)
		}
	}

	if successfulRequests >= 1 {
		responseTexts := make([]string, 0, successfulRequests)
		for _, result := range results {
			if result.responseText != "" {
				responseTexts = append(responseTexts, result.responseText)
			}
		}
		metrics := basicStats(responseTexts)
		fmt.Println("\nResponse Statistics:")
		fmt.Printf("   Length (tokens): avg=%.1f, median=%.1f, min=%d, max=%d\n",
			metrics.averageTokens, metrics.medianTokens, metrics.minimumTokens, metrics.maximumTokens)
	}
}

func boolForCSV(value bool) string {
	if value {
		return "True"
	}
	return "False"
}

func writeResults(filename string, results []probeResult) error {
	file, err := os.Create(filename)
	if err != nil {
		return err
	}
	writer := csv.NewWriter(file)
	header := []string{
		"request_number", "timestamp", "status_code", "success",
		"response_text", "error_text", "response_time_ms", "conversation_id",
	}
	if err := writer.Write(header); err != nil {
		file.Close()
		return err
	}
	for _, result := range results {
		record := []string{
			strconv.Itoa(result.requestNumber),
			result.timestamp,
			strconv.Itoa(result.statusCode),
			boolForCSV(result.success),
			result.responseText,
			result.errorText,
			strconv.FormatFloat(float64(result.responseTime.Microseconds())/1000, 'f', 3, 64),
			result.conversationID,
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

func printHeader(cfg config, delay time.Duration, concurrent bool) {
	title := "Determinism Probe - Chat Endpoint Test"
	if concurrent {
		title += " (CONCURRENT MODE)"
	}
	fmt.Println(title)
	fmt.Println(strings.Repeat("=", 60))
	fmt.Printf("Endpoint:       %s\n", cfg.url)
	fmt.Printf("Message:        %s\n", cfg.message)
	fmt.Printf("Requests:       %d\n", cfg.numRequests)
	fmt.Printf("Rate:           %g req/min (%.3fs between requests)\n", cfg.rate, delay.Seconds())
	fmt.Printf("Output:         %s\n", cfg.outputFile)
	fmt.Println(strings.Repeat("=", 60))
	fmt.Println()
}

func responseValues(httpSuccess bool, data chatData, successDefault string) (bool, string, string) {
	if httpSuccess && data.success {
		responseText := data.response
		if !data.responsePresent {
			responseText = successDefault
		}
		return true, responseText, ""
	}
	errorText := data.errorText
	if errorText == "" {
		errorText = "Unknown error"
	}
	return false, "", errorText
}

func runProbe(cfg config) error {
	delay, err := calculateDelay(cfg.rate)
	if err != nil {
		return err
	}
	printHeader(cfg, delay, false)

	client := &http.Client{Timeout: 60 * time.Second}
	results := make([]probeResult, 0, cfg.numRequests)
	rateLimited := false
	rateLimitThreshold := 0.0
	successfulRequests := 0
	startTime := time.Now()

	for requestNumber := 1; requestNumber <= cfg.numRequests; requestNumber++ {
		requestStart := time.Now()
		fmt.Printf("Request %d/%d... ", requestNumber, cfg.numRequests)

		httpSuccess, data, statusCode := sendChatMessage(client, cfg.url, cfg.message)
		responseTime := time.Since(requestStart)
		apiSuccess, responseText, errorText := responseValues(httpSuccess, data, "No response text")

		if apiSuccess {
			successfulRequests++
			fmt.Printf("OK (%.0fms)\n", responseTime.Seconds()*1000)
		} else if isRateLimit(statusCode, errorText) {
			rateLimited = true
			elapsedTime := time.Since(startTime)
			if elapsedTime > 0 {
				rateLimitThreshold = float64(requestNumber) / elapsedTime.Seconds() * 60
			}
			fmt.Printf("RATE LIMITED (status: %d)\n", statusCode)
		} else {
			fmt.Printf("Error (status: %d)\n", statusCode)
		}

		conversationID := ""
		if httpSuccess {
			conversationID = data.conversationID
		}
		results = append(results, probeResult{
			requestNumber:  requestNumber,
			timestamp:      timestampNow(),
			statusCode:     statusCode,
			success:        apiSuccess,
			responseText:   responseText,
			errorText:      errorText,
			responseTime:   responseTime,
			conversationID: conversationID,
		})

		if rateLimited {
			fmt.Printf("\n*** RATE LIMITING DETECTED at request %d ***\n", requestNumber)
			fmt.Printf("   Attempted rate: %g req/min\n", cfg.rate)
			fmt.Printf("   Actual rate achieved: %.2f req/min\n", rateLimitThreshold)
			fmt.Printf("   Status code: %d\n", statusCode)
			fmt.Printf("   Error: %s\n", errorText)
			break
		}

		if requestNumber < cfg.numRequests {
			time.Sleep(delay)
		}
	}

	totalTime := time.Since(startTime)
	actualRate := float64(len(results)) / totalTime.Seconds() * 60
	fmt.Println()
	fmt.Println(strings.Repeat("=", 60))
	fmt.Println("Test Results Summary")
	fmt.Println(strings.Repeat("=", 60))
	fmt.Printf("Total requests sent:     %d\n", len(results))
	fmt.Printf("Successful responses:    %d\n", successfulRequests)
	fmt.Printf("Failed requests:         %d\n", len(results)-successfulRequests)
	fmt.Printf("Total time:              %.2fs\n", totalTime.Seconds())
	fmt.Printf("Actual rate achieved:    %.2f req/min\n", actualRate)
	if rateLimited {
		fmt.Printf("Rate limit threshold:  ~%.2f req/min\n", rateLimitThreshold)
	}

	analyzeAndPrint(results, successfulRequests)
	fmt.Printf("\nSaving results to %s...\n", cfg.outputFile)
	if err := writeResults(cfg.outputFile, results); err != nil {
		return err
	}
	fmt.Println("Results saved successfully!")
	fmt.Println()
	return nil
}

func runProbeConcurrent(cfg config) error {
	delay, err := calculateDelay(cfg.rate)
	if err != nil {
		return err
	}
	printHeader(cfg, delay, true)

	client := &http.Client{Timeout: 60 * time.Second}
	results := make([]probeResult, 0, cfg.numRequests)
	var resultsMutex sync.Mutex
	var rateLimited atomic.Bool
	var limitInfo rateLimitInfo
	startTime := time.Now()
	var waitGroup sync.WaitGroup

	for requestNumber := 1; requestNumber <= cfg.numRequests; requestNumber++ {
		if rateLimited.Load() {
			fmt.Printf("\nStopping request launches at request %d due to rate limiting\n", requestNumber)
			break
		}
		scheduledTime := startTime.Add(time.Duration(requestNumber-1) * delay)
		waitGroup.Add(1)

		go func(number int, scheduled time.Time) {
			defer waitGroup.Done()
			if wait := time.Until(scheduled); wait > 0 {
				time.Sleep(wait)
			}
			requestStart := time.Now()
			actualDelay := requestStart.Sub(startTime)
			fmt.Printf("Request %d/%d... ", number, cfg.numRequests)

			httpSuccess, data, statusCode := sendChatMessage(client, cfg.url, cfg.message)
			responseTime := time.Since(requestStart)
			apiSuccess, responseText, errorText := responseValues(httpSuccess, data, "")

			if apiSuccess {
				fmt.Printf("OK (%.0fms, delay=%.1fs)\n", responseTime.Seconds()*1000, actualDelay.Seconds())
			} else if isRateLimit(statusCode, errorText) {
				if rateLimited.CompareAndSwap(false, true) {
					elapsedTime := time.Since(startTime)
					threshold := 0.0
					if elapsedTime > 0 {
						threshold = float64(number) / elapsedTime.Seconds() * 60
					}
					resultsMutex.Lock()
					limitInfo = rateLimitInfo{
						requestNumber: number,
						threshold:     threshold,
						statusCode:    statusCode,
						errorText:     errorText,
						elapsedTime:   elapsedTime,
					}
					resultsMutex.Unlock()
				}
				fmt.Printf("RATE LIMITED (status: %d)\n", statusCode)
			} else {
				fmt.Printf("Error (status: %d)\n", statusCode)
			}

			conversationID := ""
			if httpSuccess {
				conversationID = data.conversationID
			}
			entry := probeResult{
				requestNumber:  number,
				timestamp:      timestampNow(),
				statusCode:     statusCode,
				success:        apiSuccess,
				responseText:   responseText,
				errorText:      errorText,
				responseTime:   responseTime,
				conversationID: conversationID,
			}
			resultsMutex.Lock()
			results = append(results, entry)
			resultsMutex.Unlock()
		}(requestNumber, scheduledTime)

		if requestNumber%10 == 0 {
			time.Sleep(10 * time.Millisecond)
		}
	}

	waitGroup.Wait()
	totalTime := time.Since(startTime)
	sort.Slice(results, func(left, right int) bool {
		return results[left].requestNumber < results[right].requestNumber
	})
	successfulRequests := 0
	for _, result := range results {
		if result.success {
			successfulRequests++
		}
	}

	fmt.Println()
	fmt.Println(strings.Repeat("=", 60))
	fmt.Println("Test Results Summary")
	fmt.Println(strings.Repeat("=", 60))
	fmt.Printf("Total requests sent:     %d\n", len(results))
	fmt.Printf("Successful responses:    %d\n", successfulRequests)
	fmt.Printf("Failed requests:         %d\n", len(results)-successfulRequests)
	fmt.Printf("Total time:              %.2fs\n", totalTime.Seconds())
	fmt.Printf("Actual rate achieved:    %.2f req/min\n", float64(len(results))/totalTime.Seconds()*60)

	resultsMutex.Lock()
	info := limitInfo
	resultsMutex.Unlock()
	if rateLimited.Load() {
		fmt.Println("\nRATE LIMITING DETECTED:")
		fmt.Printf("   First rate limit at request: %d\n", info.requestNumber)
		fmt.Printf("   Time elapsed: %.2fs\n", info.elapsedTime.Seconds())
		fmt.Printf("   Rate achieved: ~%.2f req/min\n", info.threshold)
		fmt.Printf("   Status code: %d\n", info.statusCode)
		fmt.Printf("   Error: %s\n", info.errorText)
	}

	analyzeAndPrint(results, successfulRequests)
	fmt.Printf("\nSaving results to %s...\n", cfg.outputFile)
	if err := writeResults(cfg.outputFile, results); err != nil {
		return err
	}
	fmt.Println("Results saved successfully!")
	fmt.Println()
	return nil
}

func main() {
	cfg, err := parseArgs(os.Args[1:])
	if err != nil {
		fmt.Fprintf(os.Stderr, "Error: %v\n\n", err)
		usage(os.Stderr, filepath.Base(os.Args[0]))
		os.Exit(2)
	}
	if cfg.concurrent {
		err = runProbeConcurrent(cfg)
	} else {
		err = runProbe(cfg)
	}
	if err != nil {
		fmt.Fprintf(os.Stderr, "\nError: %v\n", err)
		os.Exit(1)
	}
}
