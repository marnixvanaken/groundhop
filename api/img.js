const https = require('https');
const fs = require('fs');
const path = require('path');

export default function handler(req, res) {
  const { type, id } = req.query;
  if (!type || !id || !['player', 'team', 'tournament'].includes(type)) {
    return res.status(400).send('Missing or invalid params');
  }

  // Eerst lokale cache checken
  const cached = path.join(process.cwd(), 'img', type, String(id));
  if (fs.existsSync(cached)) {
    const buf = fs.readFileSync(cached);
    res.setHeader('Content-Type', 'image/png');
    res.setHeader('Cache-Control', 'public, max-age=86400');
    return res.status(200).send(buf);
  }

  // Fallback: proxy naar Sofascore
  // Toernooien zitten bij Sofascore onder een ander pad dan de rest.
  const sfPad = type === 'tournament' ? 'unique-tournament' : type;
  const url = `https://api.sofascore.app/api/v1/${sfPad}/${id}/image`;
  const proxyReq = https.get(url, {
    headers: {
      'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
      'Referer': 'https://www.sofascore.com/',
      'Origin': 'https://www.sofascore.com',
      'Accept': 'image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8',
      'sec-fetch-dest': 'image',
      'sec-fetch-mode': 'no-cors',
      'sec-fetch-site': 'same-site',
    }
  }, (proxyRes) => {
    const chunks = [];
    proxyRes.on('data', chunk => chunks.push(chunk));
    proxyRes.on('end', () => {
      const buffer = Buffer.concat(chunks);
      res.setHeader('Content-Type', proxyRes.headers['content-type'] || 'image/png');
      res.setHeader('Cache-Control', 'public, max-age=86400');
      res.status(proxyRes.statusCode === 200 ? 200 : 404).send(buffer);
    });
  });

  proxyReq.on('error', () => res.status(404).send('Not found'));
  proxyReq.setTimeout(5000, () => { proxyReq.destroy(); res.status(504).send('Timeout'); });
}
