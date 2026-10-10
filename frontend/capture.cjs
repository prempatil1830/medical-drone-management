const puppeteer = require('puppeteer');
const fs = require('fs');

(async () => {
  console.log('Launching browser...');
  const browser = await puppeteer.launch({ headless: 'new' });
  const page = await browser.newPage();
  await page.setViewport({ width: 1920, height: 1080 });

  console.log('Navigating to login...');
  await page.goto('http://localhost:3000/login', { waitUntil: 'networkidle2' });
  await new Promise(r => setTimeout(r, 4000));
  await page.screenshot({ path: '/tmp/perf_test/login_screenshot.jpg', type: 'jpeg' });
  console.log('Saved login screenshot.');

  // Set token to bypass login
  await page.evaluate(() => {
    localStorage.setItem('token', 'fake-token-for-spike');
    localStorage.setItem('user', JSON.stringify({ role: 'admin', email: 'demo@aeromedical.in' }));
  });

  console.log('Navigating to dashboard...');
  await page.goto('http://localhost:3000/', { waitUntil: 'networkidle2' });
  await new Promise(r => setTimeout(r, 4000));

  console.log('Enabling dev data...');
  // Find dev data toggle and click it (it's the first toggle)
  const toggles = await page.$$('.toggle-switch');
  if (toggles.length > 0) {
    await toggles[0].click();
  }
  
  await new Promise(r => setTimeout(r, 2000));
  await page.screenshot({ path: '/tmp/perf_test/dashboard_frame1.jpg', type: 'jpeg' });
  console.log('Saved dashboard frame 1.');

  // Monitor performance and console errors
  const metrics = await page.metrics();
  let consoleErrors = [];
  page.on('console', msg => {
    if (msg.type() === 'error') consoleErrors.push(msg.text());
  });

  // Capture motion frames
  for (let i = 2; i <= 4; i++) {
    await new Promise(r => setTimeout(r, 1000));
    await page.screenshot({ path: `/tmp/perf_test/dashboard_frame${i}.jpg`, type: 'jpeg' });
    console.log(`Saved dashboard frame ${i}.`);
  }

  // Generate a rudimentary trace for CPU/FPS note (Puppeteer trace)
  await page.tracing.start({ path: '/tmp/perf_test/trace.json' });
  await new Promise(r => setTimeout(r, 2000));
  await page.tracing.stop();

  console.log('Console errors:', consoleErrors);
  console.log('Metrics CPU/Task duration (sec):', metrics.TaskDuration);
  
  await browser.close();
  console.log('Done.');
})();
