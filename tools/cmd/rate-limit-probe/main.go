// Command rate-limit-probe sends "Hello" messages at a specified rate to discover
// when a chat API begins throttling requests.
package main

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"sync/atomic"
	"time"
)

const defaultURL = "http://localhost:5001/api/chat"

type config struct {
	numRequests int
	rate        float64
	url         string
}

type requestResult struct {
	requestNumber int
	rateLimited   bool
	statusCode    int
	responseTime  time.Duration
	timestamp     time.Time
}

type rateLimitInfo struct {
	requestNumber int
	threshold     float64
	statusCode    int
	elapsedTime   time.Duration
}

func usage(w io.Writer, program string) {
	fmt.Fprintf(w, `Rate Limit Probe - Find the rate limit threshold

Usage:
  %s NUM_REQUESTS RATE [options]

Arguments:
  NUM_REQUESTS       Number of requests to send
  RATE               Request rate in requests per minute

Options:
  -u, --url URL      Chat API endpoint URL (default: %s)
  -h, --help         Show this help message

Examples:
  %s 50 120
  %s 200 150
  %s 100 100 -u http://example.com/api/chat
`, program, defaultURL, program, program, program)
}

// parseArgs accepts options before or after the positional arguments.
func parseArgs(args []string) (config, error) {
	cfg := config{url: defaultURL}
	positionals := make([]string, 0, 2)

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
		option, inline, hasEquals := strings.Cut(arg, "=")

		switch option {
		case "-h", "--help":
			usage(os.Stdout, filepath.Base(os.Args[0]))
			os.Exit(0)
		case "-u", "--url":
			value, err := valueFor(&index, option, inline, hasEquals)
			if err != nil {
				return cfg, err
			}
			cfg.url = value
		default:
			if strings.HasPrefix(arg, "-") {
				return cfg, fmt.Errorf("unknown option: %s", arg)
			}
			positionals = append(positionals, arg)
		}
	}

	if len(positionals) != 2 {
		return cfg, errors.New("expected NUM_REQUESTS and RATE")
	}

	var err error
	cfg.numRequests, err = strconv.Atoi(positionals[0])
	if err != nil {
		return cfg, fmt.Errorf("invalid num_requests value %q", positionals[0])
	}
	cfg.rate, err = strconv.ParseFloat(positionals[1], 64)
	if err != nil {
		return cfg, fmt.Errorf("invalid rate value %q", positionals[1])
	}
	if cfg.numRequests <= 0 {
		return cfg, errors.New("num_requests must be positive")
	}
	if cfg.rate <= 0 {
		return cfg, errors.New("rate must be positive")
	}
	return cfg, nil
}

func sendChatMessage(client *http.Client, url, message string) (bool, int) {
	payload, err := json.Marshal(struct {
		Message        string  `json:"message"`
		ConversationID *string `json:"conversation_id"`
	}{Message: message})
	if err != nil {
		return false, 0
	}

	request, err := http.NewRequest(http.MethodPost, url, bytes.NewReader(payload))
	if err != nil {
		return false, 0
	}
	request.Header.Set("Content-Type", "application/json")

	response, err := client.Do(request)
	if err != nil {
		return false, 0
	}
	defer response.Body.Close()

	rateLimited := response.StatusCode == http.StatusTooManyRequests
	if !rateLimited && response.StatusCode >= http.StatusOK && response.StatusCode < http.StatusMultipleChoices {
		var data struct {
			Error string `json:"error"`
		}
		if err := json.NewDecoder(response.Body).Decode(&data); err == nil {
			errorText := strings.ToLower(data.Error)
			rateLimited = strings.Contains(errorText, "rate limit") || strings.Contains(errorText, "too many requests")
		}
	}
	return rateLimited, response.StatusCode
}

func testRateLimit(cfg config) {
	delay := time.Duration(float64(time.Minute) / cfg.rate)

	fmt.Println("Rate Limit Probe")
	fmt.Println(strings.Repeat("=", 60))
	fmt.Printf("Endpoint:       %s\n", cfg.url)
	fmt.Println("Message:        Hello")
	fmt.Printf("Requests:       %d\n", cfg.numRequests)
	fmt.Printf("Rate:           %g req/min (%.3fs between requests)\n", cfg.rate, delay.Seconds())
	fmt.Println(strings.Repeat("=", 60))
	fmt.Println()

	client := &http.Client{Timeout: 60 * time.Second}
	results := make([]requestResult, 0, cfg.numRequests)
	var resultsMutex sync.Mutex
	var rateLimited atomic.Bool
	var stopLaunching atomic.Bool
	var limitInfo rateLimitInfo
	startTime := time.Now()
	doneChannels := make([]<-chan struct{}, 0, cfg.numRequests)

	for requestNumber := 1; requestNumber <= cfg.numRequests; requestNumber++ {
		if stopLaunching.Load() {
			break
		}

		scheduledTime := startTime.Add(time.Duration(requestNumber-1) * delay)
		done := make(chan struct{})
		doneChannels = append(doneChannels, done)

		go func(number int, scheduled time.Time) {
			defer close(done)
			if wait := time.Until(scheduled); wait > 0 {
				time.Sleep(wait)
			}

			requestStart := time.Now()
			isRateLimited, statusCode := sendChatMessage(client, cfg.url, "Hello")
			responseTime := time.Since(requestStart)

			resultsMutex.Lock()
			results = append(results, requestResult{
				requestNumber: number,
				rateLimited:   isRateLimited,
				statusCode:    statusCode,
				responseTime:  responseTime,
				timestamp:     time.Now(),
			})
			resultsMutex.Unlock()

			if isRateLimited && rateLimited.CompareAndSwap(false, true) {
				stopLaunching.Store(true)
				elapsedTime := time.Since(startTime)
				actualRate := 0.0
				if elapsedTime > 0 {
					actualRate = float64(number) / elapsedTime.Seconds() * 60
				}
				resultsMutex.Lock()
				limitInfo = rateLimitInfo{
					requestNumber: number,
					threshold:     actualRate,
					statusCode:    statusCode,
					elapsedTime:   elapsedTime,
				}
				resultsMutex.Unlock()
				fmt.Printf("\nRATE LIMIT DETECTED at request %d (after %.2fs)\n", number, elapsedTime.Seconds())
			}
		}(requestNumber, scheduledTime)

		// Give completed requests periodic opportunities to stop further launches.
		if requestNumber%10 == 0 {
			time.Sleep(10 * time.Millisecond)
		}
	}

	fmt.Printf("Launched %d request goroutines...\n", len(doneChannels))

	// Match the original script's per-request join timeout. Goroutines that are
	// still pending after their timeout do not block summary generation.
	for _, done := range doneChannels {
		select {
		case <-done:
		case <-time.After(30 * time.Second):
		}
	}

	totalTime := time.Since(startTime)
	resultsMutex.Lock()
	totalSent := len(results)
	rateLimitedCount := 0
	successfulCount := 0
	for _, result := range results {
		if result.rateLimited {
			rateLimitedCount++
		} else if result.statusCode == http.StatusOK {
			successfulCount++
		}
	}
	info := limitInfo
	resultsMutex.Unlock()

	fmt.Println()
	fmt.Println(strings.Repeat("=", 60))
	fmt.Println("Test Results")
	fmt.Println(strings.Repeat("=", 60))
	fmt.Printf("Total requests sent:     %d\n", totalSent)
	fmt.Printf("Successful responses:    %d\n", successfulCount)
	fmt.Printf("Rate limited responses:  %d\n", rateLimitedCount)
	fmt.Printf("Total time:              %.2fs\n", totalTime.Seconds())
	fmt.Printf("Average rate achieved:   %.2f req/min\n", float64(totalSent)/totalTime.Seconds()*60)

	if rateLimited.Load() {
		fmt.Println()
		fmt.Println("RATE LIMIT THRESHOLD DETECTED:")
		fmt.Printf("   First rate limit at:  Request #%d\n", info.requestNumber)
		fmt.Printf("   Time to rate limit:   %.2fs\n", info.elapsedTime.Seconds())
		fmt.Printf("   Calculated threshold: ~%.2f req/min\n", info.threshold)
		fmt.Printf("   Status code:          %d\n", info.statusCode)
	} else {
		fmt.Println()
		fmt.Println("NO RATE LIMITING DETECTED")
		fmt.Printf("   All %d requests completed successfully\n", totalSent)
		fmt.Printf("   Rate limit is above %g req/min\n", cfg.rate)
	}
	fmt.Println()
}

func main() {
	cfg, err := parseArgs(os.Args[1:])
	if err != nil {
		fmt.Fprintf(os.Stderr, "Error: %v\n\n", err)
		usage(os.Stderr, filepath.Base(os.Args[0]))
		os.Exit(2)
	}
	testRateLimit(cfg)
}
