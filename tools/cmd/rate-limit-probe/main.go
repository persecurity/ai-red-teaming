// Command rate-limit-probe sends "Hello" messages at a specified rate to discover
// when a chat API begins throttling requests.
package main

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"time"
)

const (
	defaultURL            = "http://localhost:5001/api/chat"
	defaultRequestTimeout = 5 * time.Minute
)

type config struct {
	numRequests int
	rate        float64
	url         string
	timeout     time.Duration
}

type requestResult struct {
	requestNumber int
	success       bool
	rateLimited   bool
	statusCode    int
	errorText     string
	responseTime  time.Duration
	timestamp     time.Time
}

type rateLimitInfo struct {
	requestNumber int
	threshold     float64
	statusCode    int
	elapsedTime   time.Duration
}

type rateProbeSummary struct {
	configured  int
	launched    int
	completed   int
	successful  int
	failed      int
	rateLimited int
	detected    bool
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
  -t, --timeout DURATION
                     Per-request timeout (default: %s)
  -h, --help         Show this help message

Examples:
  %s 50 120
  %s 200 150
  %s 100 100 -u http://example.com/api/chat
`, program, defaultURL, defaultRequestTimeout, program, program, program)
}

// parseArgs accepts options before or after the positional arguments.
func parseArgs(args []string) (config, error) {
	cfg := config{url: defaultURL, timeout: defaultRequestTimeout}
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
		case "-u", "--url", "-t", "--timeout":
			value, err := valueFor(&index, option, inline, hasEquals)
			if err != nil {
				return cfg, err
			}
			if option == "-u" || option == "--url" {
				cfg.url = value
			} else {
				cfg.timeout, err = time.ParseDuration(value)
				if err != nil {
					return cfg, fmt.Errorf("invalid timeout value %q", value)
				}
			}
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
	if cfg.timeout <= 0 {
		return cfg, errors.New("timeout must be positive")
	}
	return cfg, nil
}

func sendChatMessage(client *http.Client, url, message string) (bool, bool, int, string) {
	payload, err := json.Marshal(struct {
		Message        string  `json:"message"`
		ConversationID *string `json:"conversation_id"`
	}{Message: message})
	if err != nil {
		return false, false, 0, err.Error()
	}

	request, err := http.NewRequest(http.MethodPost, url, bytes.NewReader(payload))
	if err != nil {
		return false, false, 0, err.Error()
	}
	request.Header.Set("Content-Type", "application/json")

	response, err := client.Do(request)
	if err != nil {
		var networkError net.Error
		if errors.As(err, &networkError) && networkError.Timeout() {
			return false, false, 0, "Request timeout"
		}
		return false, false, 0, "Connection error: " + err.Error()
	}
	defer response.Body.Close()

	var data struct {
		Success *bool  `json:"success"`
		Error   string `json:"error"`
	}
	if err := json.NewDecoder(response.Body).Decode(&data); err != nil && response.StatusCode != http.StatusTooManyRequests {
		return false, false, response.StatusCode, "Invalid JSON response"
	}
	lowerError := strings.ToLower(data.Error)
	rateLimited := response.StatusCode == http.StatusTooManyRequests ||
		strings.Contains(lowerError, "rate limit") ||
		strings.Contains(lowerError, "too many requests")
	if rateLimited {
		return false, true, response.StatusCode, data.Error
	}
	if response.StatusCode < http.StatusOK || response.StatusCode >= http.StatusMultipleChoices {
		if data.Error == "" {
			data.Error = response.Status
		}
		return false, false, response.StatusCode, data.Error
	}
	if data.Success != nil && !*data.Success {
		if data.Error == "" {
			data.Error = "API reported an unsuccessful response"
		}
		return false, false, response.StatusCode, data.Error
	}
	return true, false, response.StatusCode, ""
}

func testRateLimit(cfg config) (rateProbeSummary, error) {
	delay := time.Duration(float64(time.Minute) / cfg.rate)
	summary := rateProbeSummary{configured: cfg.numRequests}

	fmt.Println("Rate Limit Probe")
	fmt.Println(strings.Repeat("=", 60))
	fmt.Printf("Endpoint:       %s\n", cfg.url)
	fmt.Println("Message:        Hello")
	fmt.Printf("Requests:       %d\n", cfg.numRequests)
	fmt.Printf("Rate:           %g req/min (%.3fs between requests)\n", cfg.rate, delay.Seconds())
	fmt.Printf("Timeout:        %s per request\n", cfg.timeout)
	fmt.Println(strings.Repeat("=", 60))
	fmt.Println()

	client := &http.Client{Timeout: cfg.timeout}
	results := make([]requestResult, 0, cfg.numRequests)
	var limitInfo rateLimitInfo
	startTime := time.Now()
	resultChannel := make(chan requestResult, cfg.numRequests)
	launchTimer := time.NewTimer(0)
	defer launchTimer.Stop()
	launching := true

	for launching || summary.completed < summary.launched {
		select {
		case <-launchTimer.C:
			if summary.detected || summary.launched >= cfg.numRequests {
				launching = false
				continue
			}
			summary.launched++
			requestNumber := summary.launched
			go func(number int) {
				requestStart := time.Now()
				success, isRateLimited, statusCode, errorText := sendChatMessage(client, cfg.url, "Hello")
				responseTime := time.Since(requestStart)
				resultChannel <- requestResult{
					requestNumber: number,
					success:       success,
					rateLimited:   isRateLimited,
					statusCode:    statusCode,
					errorText:     errorText,
					responseTime:  responseTime,
					timestamp:     time.Now(),
				}
			}(requestNumber)
			if summary.launched < cfg.numRequests && !summary.detected {
				launchTimer.Reset(delay)
			} else {
				launching = false
			}

		case result := <-resultChannel:
			results = append(results, result)
			summary.completed++
			switch {
			case result.rateLimited:
				summary.rateLimited++
				fmt.Printf("Request %d: RATE LIMITED (status: %d, %.0fms)\n", result.requestNumber, result.statusCode, result.responseTime.Seconds()*1000)
			case result.success:
				summary.successful++
				fmt.Printf("Request %d: OK (%.0fms)\n", result.requestNumber, result.responseTime.Seconds()*1000)
			default:
				summary.failed++
				fmt.Printf("Request %d: ERROR (status: %d, %s)\n", result.requestNumber, result.statusCode, result.errorText)
			}

			if result.rateLimited && !summary.detected {
				summary.detected = true
				if launching {
					launching = false
					if !launchTimer.Stop() {
						select {
						case <-launchTimer.C:
						default:
						}
					}
				}
				elapsedTime := time.Since(startTime)
				actualRate := 0.0
				if elapsedTime > 0 {
					actualRate = float64(result.requestNumber) / elapsedTime.Seconds() * 60
				}
				limitInfo = rateLimitInfo{
					requestNumber: result.requestNumber,
					threshold:     actualRate,
					statusCode:    result.statusCode,
					elapsedTime:   elapsedTime,
				}
				fmt.Printf("\nRATE LIMIT DETECTED at request %d (after %.2fs); stopping new launches\n", result.requestNumber, elapsedTime.Seconds())
			}
		}
	}

	totalTime := time.Since(startTime)

	fmt.Println()
	fmt.Println(strings.Repeat("=", 60))
	fmt.Println("Test Results")
	fmt.Println(strings.Repeat("=", 60))
	fmt.Printf("Requests configured:     %d\n", summary.configured)
	fmt.Printf("Requests launched:       %d\n", summary.launched)
	fmt.Printf("Requests completed:      %d\n", summary.completed)
	fmt.Printf("Successful responses:    %d\n", summary.successful)
	fmt.Printf("Failed responses:        %d\n", summary.failed)
	fmt.Printf("Rate limited responses:  %d\n", summary.rateLimited)
	fmt.Printf("Total time:              %.2fs\n", totalTime.Seconds())
	fmt.Printf("Average launch rate:     %.2f req/min\n", float64(summary.launched)/totalTime.Seconds()*60)

	if summary.detected {
		fmt.Println()
		fmt.Println("RATE LIMIT THRESHOLD DETECTED:")
		fmt.Printf("   First rate limit at:  Request #%d\n", limitInfo.requestNumber)
		fmt.Printf("   Time to rate limit:   %.2fs\n", limitInfo.elapsedTime.Seconds())
		fmt.Printf("   Calculated threshold: ~%.2f req/min\n", limitInfo.threshold)
		fmt.Printf("   Status code:          %d\n", limitInfo.statusCode)
	} else if summary.completed == summary.configured && summary.failed == 0 {
		fmt.Println()
		fmt.Println("NO RATE LIMITING DETECTED")
		fmt.Printf("   All %d requests completed successfully\n", summary.completed)
		fmt.Printf("   Rate limit is above %g req/min\n", cfg.rate)
	} else {
		fmt.Println()
		fmt.Println("RATE-LIMIT THRESHOLD COULD NOT BE DETERMINED")
		fmt.Println("   One or more requests failed or did not complete.")
	}
	fmt.Println()

	if !summary.detected && (summary.completed != summary.configured || summary.failed > 0) {
		return summary, errors.New("incomplete probe results; rate-limit threshold could not be determined")
	}
	return summary, nil
}

func main() {
	cfg, err := parseArgs(os.Args[1:])
	if err != nil {
		fmt.Fprintf(os.Stderr, "Error: %v\n\n", err)
		usage(os.Stderr, filepath.Base(os.Args[0]))
		os.Exit(2)
	}
	if _, err := testRateLimit(cfg); err != nil {
		fmt.Fprintf(os.Stderr, "Error: %v\n", err)
		os.Exit(1)
	}
}
