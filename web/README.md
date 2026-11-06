# Remote Radar dashboard

Static Next.js 16 site that renders the pipeline's JSON snapshot in `public/data/`. See the [project README](../README.md) for the full picture.

```bash
npm install
npm run dev       # http://localhost:3000
npm run lint
npm run build
```

- Data is read at build time from `public/data/*.json`. The format is specified in `../PLAN.md` (section "Published snapshot").
- `node scripts/make-sample-data.mjs` regenerates realistic sample data, marked `"sample": true`. It overwrites the real snapshot, so use it only for local UI work.
- Trend views plot only weeks with at least 20 postings (`src/lib/weeks.ts`).
