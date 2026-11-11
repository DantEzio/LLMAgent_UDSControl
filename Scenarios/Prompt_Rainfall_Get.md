Please write a Python script to fetch hourly precipitation data for the Chaohu (巢湖) region from the Open-Meteo Historical Weather Archive API, and save the results as an Excel file.

## API Information

- API Endpoint: https://archive-api.open-meteo.com/v1/archive
- This is a free historical weather data API provided by Open-Meteo, based on ERA5 reanalysis data (ECMWF's global reanalysis dataset), with a spatial resolution of approximately 0.25° (~25 km grid). No API key is required.
- Official documentation: https://open-meteo.com/en/docs/historical-weather-api

## Request Parameters

- Latitude: 31.6 (Chaohu city center area)
- Longitude: 117.87 (Chaohu city center area)
- Start date: 2015-01-01
- End date: 2025-06-10
- Hourly variable: precipitation (precipitation amount in mm)
- Timezone: Asia/Shanghai (UTC+8, ensures timestamps are consistent with Beijing time)

## Output Requirements

Save the retrieved data as an Excel file named `Chaohu_Rainfall_2015-2025_OpenMeteo.xlsx`, containing the following 3 worksheets:

### Sheet 1: Hourly_Rainfall (Hourly Precipitation Data)

Each row represents one hour of precipitation record, with the following column structure:

| Column | Description | Example |
|--------|-------------|---------|
| datetime | Full date and time (Asia/Shanghai timezone) | 2015-01-01 00:00:00 |
| date | Date portion | 2015-01-01 |
| time | Time portion | 00:00 |
| year | Year | 2015 |
| month | Month | 1 |
| day | Day | 1 |
| hour | Hour | 0 |
| precipitation_mm | Precipitation amount (millimeters) | 0.0 |

Total rows should be approximately 91,536 (2015-01-01 00:00 to 2025-06-10 23:00, ~10.5 years × 365.25 days × 24 hours).

### Sheet 2: Yearly_Stats (Annual Statistics)

Aggregate precipitation data by year, with the following columns:

| Column | Description |
|--------|-------------|
| year | Year |
| total_precipitation_mm | Annual total precipitation (mm) |
| max_hourly_precipitation_mm | Annual maximum hourly precipitation (mm) |
| rainy_hours | Number of hours with precipitation (precipitation > 0) |
| rainy_days | Number of days with precipitation (daily total > 0) |

### Sheet 3: Monthly_Stats (Monthly Statistics)

Aggregate precipitation data by year-month, with the following columns:

| Column | Description |
|--------|-------------|
| year | Year |
| month | Month |
| total_precipitation_mm | Monthly total precipitation (mm) |
| max_hourly_precipitation_mm | Monthly maximum hourly precipitation (mm) |
| rainy_hours | Number of hours with precipitation (precipitation > 0) |

Total rows should be approximately 126 (10.5 years × 12 months).

## Technical Requirements

1. Use the `requests` library to call the API (GET request, parameters passed via query string)
2. Use `pandas` for data processing and organization
3. Use `openpyxl` or `pandas.ExcelWriter` to save the Excel file
4. Implement a request retry mechanism (at least 3 retries with 5-second intervals) to handle network timeouts and API rate limiting
5. After receiving the response, print the JSON structure keys to confirm data integrity
6. Check the precipitation column for NaN values; if any are found, fill them with 0
7. After saving, read the Excel file back and verify that the row counts of all three sheets are correct
8. Print a final summary: total rows, time range, total precipitation, maximum hourly precipitation, number of rainy hours

## Notes

- ERA5 reanalysis data is gridded data, not station observation data. The coordinates 31.6°N, 117.87°E will be mapped to the nearest grid cell
- The precipitation variable is measured in millimeters (mm), representing the precipitation amount for that hour
- The API returns time strings in ISO 8601 format (e.g., "2015-01-01T00:00"), which need to be parsed into datetime objects
- When timezone=Asia/Shanghai is set, the API returns timestamps already in UTC+8; no additional conversion is needed
- The data volume is large (~91,000 rows) but can be retrieved in a single request. If a timeout occurs, consider splitting the request by year and merging the results afterward