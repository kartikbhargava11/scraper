# Web APP to scrape the websites

A python based web application to scrape the internal links or extract HTML markup for any given URL.

## Features

1. **Link Extraction**: Discovers and maps all internal links on a target website.
2. **HTML Scraping**: Fetches and extracts structured HTML markup.


## Requirements
1. **Python** >=3.13
2. **Docker**
3. **Web Browser**: Chrome or Firefox or Edge (for Testing)
4. **Terminal** (To run the commands)
5. **Code Editor**

## Installation and Setup
Follow these step to get the application running locally

### 1. Open the Terminal and go to the desired folder 
```cd <dir-name>```

### 2. Clone the Repository 
```git clone https://github.com/kartikbhargava11/scraper.git```

### 3. Move to the Folder Directory
```cd scraper```

### 4. Build the Docker Containers from scratch without cached layers to ensure everything is up-to-date
```docker-compose build --no-cache```

### 5. Start the Application
```docker-compose up```

### 6. Stopping the Application
```docker-compose down```