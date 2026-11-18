// Package msg holds the agent's own messages — the sentences it writes into a
// command's result, as opposed to what a Windows tool prints — as a code the
// console words in its reader's language, with the French text beside it.
//
// The result the agent posts carries both (models.CommandResult): the text in
// output or error, as it always did, which is what an older server stores and
// shows; and message_code with message_params, which a server that knows them
// stores beside the text for the console to word (plan
// dev/plan-console-bilingue.md, I5). The code words the error of a failed
// result and the output of a succeeded one — the whole text, never part of it:
// a coded message wrapped in an uncoded sentence travels without its code.
//
// Every French sentence is written in this package (catalogue.go) and nowhere
// else, from its parameters: the console's catalogue must read the same, word
// for word, and the shared cases in testdata/messages_fr.json prove it on both
// sides. What a Windows tool printed stays as Windows wrote it, in a parameter
// (detail, summary) when a sentence quotes it.
package msg

import (
	"encoding/json"
	"errors"
	"fmt"
	"maps"
	"strings"
	"unicode/utf8"
)

// Params fills a message: a few flat values — text, whole numbers, booleans.
// The server drops a message whose parameters are anything else.
type Params map[string]any

// Message is a sentence of the agent's: its code, its parameters, and the
// French text.
//
// A Message without a code is plain text — a tool's output, or a sentence
// too composite to word from a code — and travels as text alone.
type Message struct {
	Code   string
	Params Params
	Text   string
}

// Plain is text without a code.
func Plain(text string) Message {
	return Message{Text: text}
}

// New is the message of a code, its French written from params. A code
// missing from the catalogue is a programming error the tests catch
// (TestEveryCodeInTheSourceIsInTheCatalogue); at run time it degrades to the
// code itself as text, without a code — never a panic in the service.
func New(code string, params Params) Message {
	write, ok := french[code]
	if !ok {
		return Plain(code)
	}
	if params == nil {
		params = Params{}
	}
	return Message{Code: code, Params: params, Text: write(params)}
}

// Error is an error whose whole text is a message of the agent's.
type Error struct {
	Message
	cause error
}

func (e *Error) Error() string { return e.Text }

// Unwrap is the error the message reports on, if any: errors.Is and
// errors.As see through the message as they did through fmt.Errorf's %w.
func (e *Error) Unwrap() error { return e.cause }

// Err is the error of a code.
func Err(code string, params Params) *Error {
	return &Error{Message: New(code, params)}
}

// Wrap is the error of a code reporting on cause, whose own text the
// sentence quotes as params["detail"] (set here when absent).
//
// A cause that is itself a coded message of the agent's hands on its code
// and parameters too — "detail_code", and each parameter as "detail_<name>"
// — so that the console words the detail in its reader's language, as it
// words the sentence around it (verification of 2026-11-18: it showed the
// French text inside an English sentence).
func Wrap(code string, params Params, cause error) *Error {
	p := Params{}
	maps.Copy(p, params)
	if _, ok := p["detail"]; !ok && cause != nil {
		p["detail"] = cause.Error()
		if inner, innerParams := Of(cause); inner != "" {
			p["detail_code"] = inner
			for k, v := range innerParams {
				if !strings.HasPrefix(k, "detail") {
					p["detail_"+k] = v
				}
			}
		}
	}
	return &Error{Message: New(code, p), cause: cause}
}

// Of is the code and parameters of err, when err's whole text is a coded
// message that fits what the server keeps (Fits); "" and nil otherwise — an
// uncoded error, or a coded one inside a longer sentence.
func Of(err error) (string, Params) {
	var e *Error
	if err == nil || !errors.As(err, &e) || e.Code == "" || e.Error() != err.Error() {
		return "", nil
	}
	return Coded(e.Message)
}

// Coded is m's code and parameters, or "" and nil when it has none or when
// its parameters exceed what the server keeps — the text then goes alone,
// as it would from an older agent.
func Coded(m Message) (string, Params) {
	if m.Code == "" || !Fits(m.Params) {
		return "", nil
	}
	return m.Code, m.Params
}

// The server's bounds on message_params (backend command/texts.py,
// clean_message), with a margin on the whole for its own serialisation.
const (
	maxParams       = 16
	maxParamRunes   = 1024
	maxParamsBytes  = 3500
	maxParamKeySize = 32
)

// Fits reports whether params stay within what the server keeps: a quoted
// tool error can be long, and a dropped code beats a refused result.
func Fits(params Params) bool {
	if len(params) > maxParams {
		return false
	}
	for k, v := range params {
		if len(k) == 0 || len(k) > maxParamKeySize {
			return false
		}
		if s, ok := v.(string); ok && utf8.RuneCountInString(s) > maxParamRunes {
			return false
		}
	}
	data, err := json.Marshal(params)
	return err == nil && len(data) <= maxParamsBytes
}

// Quote writes a value the way the sentences have always quoted one
// (fmt's %q), for a parameter that is shown quoted.
func Quote(value string) string {
	return fmt.Sprintf("%q", value)
}
