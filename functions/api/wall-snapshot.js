// AN156 staging: serves the private R2 snapshot through the Pages project. Same origin; the bucket has no public URL.
// Binding WALL_BUCKET is set in wrangler.toml (bucket atd-wall-staging). Read-only: GET only.
export async function onRequestGet(context) {
  const obj = await context.env.WALL_BUCKET.get('wall/snapshot.json.gz');
  if (!obj) {
    return new Response('snapshot not published yet', { status: 404, headers: { 'cache-control': 'no-store' } });
  }
  return new Response(obj.body, {
    status: 200,
    headers: {
      'content-type': 'application/octet-stream',   // gzip bytes; the page decompresses them itself
      'cache-control': 'no-store',                   // staleness is judged in the browser, so never cache here
      'x-snapshot-uploaded': obj.uploaded ? obj.uploaded.toISOString() : '',
    },
  });
}
