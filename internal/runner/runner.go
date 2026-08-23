package runner

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"os/exec"
	"strings"
)

type Result struct {
	Stdout string
	Stderr string
	Code   int
}

type Runner interface {
	Run(ctx context.Context, name string, args ...string) (Result, error)
}

type Exec struct{}

func (Exec) Run(ctx context.Context, name string, args ...string) (Result, error) {
	cmd := exec.CommandContext(ctx, name, args...)
	var stdout, stderr bytes.Buffer
	cmd.Stdout = &stdout
	cmd.Stderr = &stderr
	err := cmd.Run()
	result := Result{Stdout: stdout.String(), Stderr: stderr.String()}
	if err == nil {
		return result, nil
	}
	var exitErr *exec.ExitError
	if errors.As(err, &exitErr) {
		result.Code = exitErr.ExitCode()
		return result, fmt.Errorf("%s %s failed with exit code %d: %s", name, strings.Join(args, " "), result.Code, strings.TrimSpace(result.Stderr))
	}
	return result, err
}

type Fake struct {
	Responses map[string]Result
	Calls     []string
}

func NewFake(responses map[string]Result) *Fake {
	if responses == nil {
		responses = map[string]Result{}
	}
	return &Fake{Responses: responses}
}

func (f *Fake) Run(_ context.Context, name string, args ...string) (Result, error) {
	key := strings.TrimSpace(name + " " + strings.Join(args, " "))
	f.Calls = append(f.Calls, key)
	result, ok := f.Responses[key]
	if !ok {
		return Result{Code: 127}, fmt.Errorf("fake runner has no response for %q", key)
	}
	if result.Code != 0 {
		return result, fmt.Errorf("%s failed with exit code %d: %s", key, result.Code, strings.TrimSpace(result.Stderr))
	}
	return result, nil
}
