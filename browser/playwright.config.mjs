import {defineConfig,devices} from '@playwright/test';
export default defineConfig({
 testDir:'./e2e',timeout:60000,retries:process.env.CI?1:0,workers:1,
 use:{baseURL:'http://127.0.0.1:4175',...devices['Desktop Chrome'],trace:'retain-on-failure',screenshot:'only-on-failure',...(process.env.BROWSER_EXECUTABLE?{launchOptions:{executablePath:process.env.BROWSER_EXECUTABLE}}:{})},
 webServer:{command:'npm run serve',url:'http://127.0.0.1:4175',reuseExistingServer:!process.env.CI}
});
