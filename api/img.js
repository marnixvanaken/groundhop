const https = require('https');

export default function handler(req, res) {
  const { type, id } = req.query;
  if (!type || !id || !['player', 'team'].includes(type)) {
    return res.status(400).send('Missing or invalid params');
  }

  const url = `https://api.sofascore.app/api/v1/${type}/${id}/image`;

  const proxyReq = https.get(url, {
    headers: {
      'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
      'Referer': 'https://www.sofascore.com/',
      'Origin': 'https://www.sofascore.com',
      'Accept': 'image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8',
      'Accept-Language': 'nl-NL,nl;q=0.9,en-US;q=0.8,en;q=0.7',
      'Accept-Encoding': 'gzip, deflate, br',
      'sec-ch-ua': '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
      'sec-ch-ua-mobile': '?0',
      'sec-ch-ua-platform': '"Windows"',
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
