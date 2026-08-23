package main

import (
	"context"
	"fmt"
	"os"

	"github.com/vecyang1/gtm-agent-cli/internal/cli"
)

func main() {
	cmd := cli.NewRoot(cli.Options{})
	if err := cmd.ExecuteContext(context.Background()); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
