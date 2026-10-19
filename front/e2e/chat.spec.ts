import { expect, test } from '@playwright/test'
import { chatFixture } from '../src/test/fixtures'

test('chat con teclado, contrato relativo y metadatos reales de la respuesta', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await page.route('**/api/chat', async (route) => {
    expect(route.request().method()).toBe('POST')
    expect(route.request().postDataJSON()).toEqual({ mensaje: 'No tengo internet' })
    await route.fulfill({ json: chatFixture })
  })
  await page.goto('/')
  await page.getByRole('textbox', { name: 'Tu consulta' }).fill('No tengo internet')
  await page.getByRole('textbox').press('Enter')
  await expect(page.getByText(chatFixture.respuesta)).toBeVisible()
  await page.getByText('Detalles de la clasificación').click()
  await expect(page.getByText('42,75 ms')).toBeVisible()
  await expect(page.getByText('87,32%')).toBeVisible()
  await expect(page.locator('canvas')).toHaveCount(0)
  const resources = await page.evaluate(() => performance.getEntriesByType('resource').map((entry) => entry.name))
  expect(resources.some((url) => url.includes('/assets/OrbScene-'))).toBe(false)
})

test('móvil sin desbordamiento y sugerencias accesibles', async ({ page }) => {
  await page.setViewportSize({ width: 360, height: 800 })
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await page.goto('/')
  await page.getByRole('button', { name: /Mi factura/ }).click()
  await expect(page.getByRole('textbox')).toBeFocused()
  await expect(page.getByRole('textbox')).toHaveValue('Quiero revisar mi factura')
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
})

test('WebGL no disponible no impide conversar', async ({ page }) => {
  await page.addInitScript(() => {
    const original = HTMLCanvasElement.prototype.getContext
    HTMLCanvasElement.prototype.getContext = function (this: HTMLCanvasElement, type: string, ...args: unknown[]) {
      if (type.startsWith('webgl') || type === 'experimental-webgl') return null
      return Reflect.apply(original, this, [type, ...args])
    } as typeof original
  })
  await page.route('**/api/chat', (route) => route.fulfill({ json: chatFixture }))
  await page.goto('/')
  await expect(page.locator('[data-testid="orb-fallback"][data-reason="unavailable"]')).toBeVisible()
  await page.getByRole('textbox').fill('Consulta sin WebGL')
  await page.getByRole('button', { name: 'Enviar consulta' }).click()
  await expect(page.getByText(chatFixture.respuesta)).toBeVisible()
})

test('un error del gateway no borra la consulta ni crea resultados', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await page.route('**/api/chat', (route) => route.fulfill({ status: 502, contentType: 'text/html', body: '<h1>Bad Gateway</h1>' }))
  await page.goto('/')
  await page.getByRole('textbox').fill('Mi consulta de prueba')
  await page.getByRole('textbox').press('Enter')
  await expect(page.getByRole('alert')).toContainText('HTTP 502')
  await expect(page.getByRole('log')).toContainText('Mi consulta de prueba')
  await expect(page.getByText('Detalles de la clasificación')).toHaveCount(0)
  await expect(page.getByRole('button', { name: /Reenviar consulta/ })).toBeEnabled()
})

test('la esfera WebGL se renderiza sin errores y reacciona a una consulta', async ({ page }) => {
  const errors: string[] = []
  page.on('pageerror', (error) => errors.push(error.message))
  page.on('console', (message) => { if (message.type() === 'error') errors.push(message.text()) })
  await page.emulateMedia({ reducedMotion: 'no-preference' })
  await page.route('**/api/chat', (route) => route.fulfill({ json: chatFixture }))
  await page.goto('/')
  await expect(page.locator('.orb-stage canvas')).toBeVisible()
  // Canvas conserva su contenido de respaldo en el DOM aunque WebGL esté activo.
  await expect(page.getByTestId('orb-fallback')).toBeHidden()
  await page.getByRole('textbox').fill('Consulta con esfera')
  await page.getByRole('textbox').press('Enter')
  await expect(page.locator('.orb-stage')).toHaveClass(/phase-success/)
  await expect(page.getByText(chatFixture.respuesta)).toBeVisible()
  expect(errors).toEqual([])
})

test('un fallo al descargar Three.js mantiene el chat operativo', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'no-preference' })
  await page.route('**/assets/OrbScene-*.js', (route) => route.abort())
  await page.route('**/api/chat', (route) => route.fulfill({ json: chatFixture }))
  await page.goto('/')
  await expect(page.locator('[data-reason="unavailable"]')).toBeVisible()
  await page.getByRole('textbox').fill('Consulta sin descargar Three.js')
  await page.getByRole('textbox').press('Enter')
  await expect(page.getByText(chatFixture.respuesta)).toBeVisible()
})

test('la pérdida del contexto WebGL activa el fallback sin borrar el chat', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'no-preference' })
  await page.goto('/')
  const canvas = page.locator('.orb-stage canvas')
  await expect(canvas).toBeVisible()
  await page.getByRole('textbox').fill('Borrador que debe conservarse')
  const contextLost = await canvas.evaluate((element: HTMLCanvasElement) => {
    const extension = element.getContext('webgl2')?.getExtension('WEBGL_lose_context')
    extension?.loseContext()
    return !!extension
  })
  expect(contextLost).toBe(true)
  await expect(page.locator('[data-reason="unavailable"]')).toBeVisible()
  await expect(page.getByRole('textbox')).toHaveValue('Borrador que debe conservarse')
})
