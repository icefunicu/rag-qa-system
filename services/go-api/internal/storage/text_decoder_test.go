package storage

import (
	"testing"
	"unicode/utf16"
)

func TestDecodeTextPayloadUTF8(t *testing.T) {
	text, encoding := decodeTextPayload([]byte("你好，RAG"))
	if encoding != "utf-8" {
		t.Fatalf("expected utf-8, got %s", encoding)
	}
	if text != "你好，RAG" {
		t.Fatalf("unexpected text: %q", text)
	}
}

func TestDecodeTextPayloadGB18030(t *testing.T) {
	payload := []byte{0xC4, 0xE3, 0xBA, 0xC3, 0xA3, 0xAC, 0x52, 0x41, 0x47}
	text, encoding := decodeTextPayload(payload)
	if encoding != "gb18030" && encoding != "gbk" {
		t.Fatalf("expected gb18030/gbk, got %s", encoding)
	}
	if text != "你好，RAG" {
		t.Fatalf("unexpected text: %q", text)
	}
}

func TestDecodeTextPayloadUTF16LE(t *testing.T) {
	words := utf16.Encode([]rune("中文预览"))
	payload := make([]byte, 0, len(words)*2+2)
	payload = append(payload, 0xFF, 0xFE)
	for _, word := range words {
		payload = append(payload, byte(word), byte(word>>8))
	}

	text, encoding := decodeTextPayload(payload)
	if encoding != "utf-16le" {
		t.Fatalf("expected utf-16le, got %s", encoding)
	}
	if text != "中文预览" {
		t.Fatalf("unexpected text: %q", text)
	}
}
