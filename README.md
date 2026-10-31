# ✈️ Bot Cazador de Vuelos: Buenos Aires ⇄ Miami (Febrero 2027)

Bot automatizado en Python + Playwright que consulta **cada 1 hora** las 4 plataformas solicitadas:
1. **Skyscanner Argentina** (`skyscanner.com.ar`)
2. **Turismocity** (`turismocity.com.ar`)
3. **Cheapflights** (`cheapflights.com`)
4. **Google Flights** (`google.com/travel/flights?gl=AR&hl=es-419`)

---

## 🎯 Filtros configurados en el Bot

- **Ida (Buenos Aires `BUE/EZE/AEP` ➔ Miami `MIA`)**:
  - **05/02/2027**: Salida entre las **18:00 hs y las 23:59 hs**
  - **06/02/2027**: Todo el día (**00:00 hs a 23:59 hs**)
  - **07/02/2027**: Salida hasta las **16:00 hs** (**00:00 hs a 16:00 hs**)
- **Vuelta (Miami `MIA` ➔ Buenos Aires `BUE/EZE/AEP`)**:
  - **20/02/2027**: Salida a partir de las **17:00 hs** (**17:00 hs a 23:59 hs**)
  - **21/02/2027**: Todo el día (**00:00 hs a 23:59 hs**)
- **Equipaje**: Incluyendo **Carry-on** (equipaje de mano).
- **Escalas**: **Directo (0 escalas)** o con **1 escala** como máximo.
- **Condición de Alerta por Email**:
  - Tramos individuales (Ida o Vuelta por separado): **< USD 450**
  - Pasajes Ida y Vuelta combinados: **< USD 900 total** (< USD 450 promedio por tramo)

---

## 🚀 Instalación y Puesta en Marcha

### 1. Instalar dependencias de Python
Abrí una terminal en esta carpeta y ejecutá:

```powershell
python -m pip install -r requirements.txt
```
*(El bot utiliza directamente tu instalación de **Google Chrome** o **Microsoft Edge** mediante Chrome DevTools Protocol en Python puro, por lo que no es bloqueado por las políticas de Control de Aplicaciones de Windows).*

### 2. Configurar tu correo Gmail (`.env`)
1. Copiá el archivo `.env.example` con el nombre `.env`:
   ```powershell
   copy .env.example .env
   ```
2. Entrá a tu cuenta de Google en [Contraseñas de aplicación (App Passwords)](https://myaccount.google.com/apppasswords).
3. Creá una clave llamada `"Bot Vuelos"` y pegá los 16 caracteres en `SMTP_PASSWORD` dentro del archivo `.env`.

### 3. Comandos útiles

- **Ver todos los links directos pre-filtrados** (para abrirlos en tu navegador cuando quieras):
  ```powershell
  python main.py --show-links
  ```
- **Probar el envío de mail**:
  ```powershell
  python main.py --test-email
  ```
- **Ejecutar una búsqueda completa una sola vez**:
  ```powershell
  python main.py --once
  ```
- **Dejar el bot corriendo cada 1 hora automáticamente**:
  ```powershell
  python main.py
  ```
  *(O hacé doble clic en `run_bot.bat`)*.
