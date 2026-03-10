# Image-Rich Document Support

This repository supports screenshot-heavy enterprise documents in the KB ingest pipeline.

## Supported Upload Types

- `txt`
- `pdf`
- `docx`
- `png`
- `jpg`
- `jpeg`

## Runtime Configuration

- `VISION_PROVIDER` sets the primary OCR provider. Default: `local`
- `VISION_FALLBACK_PROVIDER` sets the fallback provider. Default: `external`
- `VISION_TESSERACT_CMD` configures the local OCR binary path
- `VISION_TESSERACT_LANG` configures local OCR languages. Default: `eng+chi_sim`
- `VISION_API_BASE_URL`, `VISION_API_KEY`, `VISION_MODEL` configure the external vision provider
- `VISION_TIMEOUT_SECONDS` controls OCR request timeout
- `VISION_MAX_ASSETS_PER_DOCUMENT` limits extracted screenshots per document
- `VISION_THUMBNAIL_MAX_EDGE_PX` controls generated thumbnail size

## Public API Additions

- `GET /api/v1/kb/documents/{document_id}/visual-assets`
- `GET /api/v1/kb/visual-assets/{asset_id}/thumbnail`

Citation payloads from retrieve, query, and chat may include:

- `evidence_kind`
- `source_kind`
- `page_number`
- `asset_id`
- `thumbnail_url`

## Behavior Notes

- Text parsing remains the primary path.
- Visual OCR runs asynchronously after the base lexical index is available.
- If visual OCR fails, the document can still remain queryable when textual chunks exist.
- Image-only documents require visual OCR to produce queryable chunks.
- Screenshot citations resolve to a stable thumbnail route instead of an expiring presigned thumbnail URL.
