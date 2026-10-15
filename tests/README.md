# Tests

Run `make ci` from the repository root. Tests cover intake, OCR, extraction,
review, registration, HTTP access, exports, and JSON Schema contracts.
Synthetic inputs are created in temporary directories and removed after tests;
no demonstration or research dataset ships with the application.
The Tesseract integration test skips when its dependencies are unavailable.
