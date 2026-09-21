const https = require('https');

exports.handler = async (event) => {
  const { type, id } = event.queryStringParameters || {};
  if (!type || !id || !['player', 'team', 'tournament'].includes(type)) {
    return { statusCode: 400, body: 'Missing or invalid params' };
  }

  // Toernooien zitten bij Sofascore onder een ander pad dan de rest.
  const sfPad = type === 'tournament' ? 'unique-tournament' : type;
  const url = `https://api.sofascore.app/api/v1/${sfPad}/${id}/image`;

  return new Promise((resolve) => {
    const req = https.get(url, {
      headers: {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Referer': 'https://www.sofascore.com/',
      }
    }, (res) => {
      const chunks = [];
      res.on('data', chunk => chunks.push(chunk));
      res.on('end', () => {
        const buffer = Buffer.concat(chunks);
        resolve({
          statusCode: res.statusCode === 200 ? 200 : 404,
          headers: {
            'Content-Type': res.headers['content-type'] || 'image/png',
            'Cache-Control': 'public, max-age=86400',
          },
          body: buffer.toString('base64'),
          isBase64Encoded: true,
        });
      });
    });
    req.on('error', () => resolve({ statusCode: 404, body: 'Not found' }));
    req.setTimeout(5000, () => { req.destroy(); resolve({ statusCode: 504, body: 'Timeout' }); });
  });
};
