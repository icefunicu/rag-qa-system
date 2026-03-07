package storage

import (
	"bytes"
	"encoding/binary"
	"unicode/utf16"
	"unicode/utf8"

	"golang.org/x/text/encoding"
	"golang.org/x/text/encoding/simplifiedchinese"
	"golang.org/x/text/transform"
)

type TextReadResult struct {
	Text      string
	Encoding  string
	Truncated bool
}

func decodeTextPayload(payload []byte) (string, string) {
	if len(payload) == 0 {
		return "", "utf-8"
	}

	switch {
	case bytes.HasPrefix(payload, []byte{0xEF, 0xBB, 0xBF}):
		return string(payload[3:]), "utf-8-sig"
	case bytes.HasPrefix(payload, []byte{0xFF, 0xFE}):
		return decodeUTF16(payload[2:], binary.LittleEndian), "utf-16le"
	case bytes.HasPrefix(payload, []byte{0xFE, 0xFF}):
		return decodeUTF16(payload[2:], binary.BigEndian), "utf-16be"
	}

	if decoded, ok := decodeUTF8(payload); ok {
		return decoded, "utf-8"
	}

	if looksLikeUTF16(payload) {
		if zeroesAtOddIndexes(payload) >= zeroesAtEvenIndexes(payload) {
			return decodeUTF16(payload, binary.LittleEndian), "utf-16le"
		}
		return decodeUTF16(payload, binary.BigEndian), "utf-16be"
	}

	if decoded, ok := decodeWithDecoder(payload, func() *encoding.Decoder {
		return simplifiedchinese.GB18030.NewDecoder()
	}); ok {
		return decoded, "gb18030"
	}

	if decoded, ok := decodeWithDecoder(payload, func() *encoding.Decoder {
		return simplifiedchinese.GBK.NewDecoder()
	}); ok {
		return decoded, "gbk"
	}

	return string(bytes.ToValidUTF8(payload, []byte("\uFFFD"))), "utf-8-fallback"
}

func decodeUTF8(payload []byte) (string, bool) {
	for trim := 0; trim <= 3 && trim < len(payload); trim++ {
		candidate := payload[:len(payload)-trim]
		if utf8.Valid(candidate) {
			return string(candidate), true
		}
	}
	return "", false
}

func decodeUTF16(payload []byte, order binary.ByteOrder) string {
	if len(payload) < 2 {
		return ""
	}
	if len(payload)%2 != 0 {
		payload = payload[:len(payload)-1]
	}

	words := make([]uint16, 0, len(payload)/2)
	for idx := 0; idx+1 < len(payload); idx += 2 {
		words = append(words, order.Uint16(payload[idx:idx+2]))
	}

	return string(utf16.Decode(words))
}

func looksLikeUTF16(payload []byte) bool {
	if len(payload) < 4 {
		return false
	}

	evenZeroes := zeroesAtEvenIndexes(payload)
	oddZeroes := zeroesAtOddIndexes(payload)
	threshold := len(payload) / 4
	return evenZeroes >= threshold || oddZeroes >= threshold
}

func zeroesAtEvenIndexes(payload []byte) int {
	count := 0
	for idx := 0; idx < len(payload); idx += 2 {
		if payload[idx] == 0 {
			count++
		}
	}
	return count
}

func zeroesAtOddIndexes(payload []byte) int {
	count := 0
	for idx := 1; idx < len(payload); idx += 2 {
		if payload[idx] == 0 {
			count++
		}
	}
	return count
}

func decodeWithDecoder(payload []byte, newDecoder func() *encoding.Decoder) (string, bool) {
	for trim := 0; trim <= 3 && trim < len(payload); trim++ {
		candidate := payload[:len(payload)-trim]
		decoded, _, err := transform.String(newDecoder(), string(candidate))
		if err == nil {
			return decoded, true
		}
	}
	return "", false
}
