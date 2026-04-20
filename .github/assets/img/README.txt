NBADB website assets (revised no-crop set)

This revision keeps the icon and logo as the same full mark.
Nothing is cropped to a sub-part of the logo.

Files
- logo-full.png
- logo-full@2x.png
- logo-full-600.png
- icon-512.png
- icon-192.png
- icon-maskable-512.png
- favicon.ico
- favicon-32x32.png
- favicon-16x16.png
- apple-touch-icon.png
- apple-touch-icon-transparent.png
- android-chrome-192x192.png
- android-chrome-512x512.png
- texture-docs-ambient.png
- polish-plate-base.png
- hero-homepage.png
- backplate-social-1344x704.png
- og-image-1200x630.png
- social-preview-wide.png
- site.webmanifest
- head-snippet.html
- social-meta-snippet.html
- head-snippet-with-social.html

Notes
- The icon/favicon set now uses the full logo mark fitted into a square.
- The favicon is less simplified than the cropped-ball version, by request.
- `texture-docs-ambient.png` is the Draw Things-generated ambient plate used in the docs shell.
- `polish-plate-base.png` is deprecated and should not be reused; it contains artifacted/generated text and is kept only as process history.
- `hero-homepage.png` and `backplate-social-1344x704.png` remain the source masters for the homepage/social backplates.
- The live homepage court panel now layers `hero-homepage.png` at low opacity under the court treatment instead of leaving the master unused in `docs/public/`.
- `og-image-1200x630.png` and `social-preview-wide.png` are legacy branded derivatives; the live root metadata now prefers the generated `docs/app/opengraph-image.tsx` route.
- The legacy `section-*.png` plate set was retired once homepage cards switched to deterministic CSS gradients.
- `.github/assets/img/` is the source-of-truth asset workspace; `docs/public/` mirrors shipped copies when filenames overlap.
- The two latest dev-doc concept images remain excluded.
