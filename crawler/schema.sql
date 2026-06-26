DROP TABLE IF EXISTS user;
DROP TABLE IF EXISTS website;
DROP TABLE IF EXISTS internal_url;
DROP TABLE IF EXISTS markup;
DROP TABLE IF EXISTS title_tag;
DROP TABLE IF EXISTS h1_tag;
DROP TABLE IF EXISTS h2_tag;
DROP TABLE IF EXISTS img_alt_tag;
DROP TABLE IF EXISTS crawl_job;

CREATE TABLE user (
    user_id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password TEXT NOT NULL
);

-- Rule: Flask creates a job, Celery executes that job. Celery updates that job.
CREATE TABLE crawl_job (
    job_id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT,
    job_type TEXT NOT NULL,
    job_status TEXT NOT NULL DEFAULT 'PENDING',
    error_message TEXT,
    created TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMP,
    finished_at TIMESTAMP
);


CREATE TABLE website (
    website_id INTEGER PRIMARY KEY AUTOINCREMENT,
    website_url TEXT NOT NULL,
    job_id INTEGER NOT NULL UNIQUE,
    FOREIGN KEY (job_id) REFERENCES crawl_job (job_id) ON DELETE CASCADE
);

CREATE TABLE internal_url (
    url_id INTEGER PRIMARY KEY AUTOINCREMENT,
    url_address TEXT NOT NULL,
    depth INTEGER DEFAULT NULL,
    job_id INTEGER NOT NULL,
    FOREIGN KEY (job_id) REFERENCES crawl_job (job_id) ON DELETE CASCADE
);

CREATE TABLE markup (
    markup_id INTEGER PRIMARY KEY AUTOINCREMENT,
    html TEXT,
    url_id INTEGER NOT NULL,
    job_id INTEGER NOT NULL,
    status_code INTEGER,
    final_crawled_url TEXT,
    redirected_status_code INTEGER,
    crawling_error_message TEXT,
    FOREIGN KEY (url_id) REFERENCES internal_url (url_id),
    FOREIGN KEY (job_id) REFERENCES crawl_job (job_id) ON DELETE CASCADE
);

CREATE TABLE title_tag (
    title_tag_id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    url_id INTEGER NOT NULL,
    FOREIGN KEY (url_id) REFERENCES internal_url (url_id) ON DELETE CASCADE
);

CREATE TABLE h1_tag (
    h1_tag_id INTEGER PRIMARY KEY AUTOINCREMENT,
    h1 TEXT NOT NULL,
    url_id INTEGER NOT NULL,
    FOREIGN KEY (url_id) REFERENCES internal_url (url_id) ON DELETE CASCADE
);

CREATE TABLE h2_tag (
    h2_tag_id INTEGER PRIMARY KEY AUTOINCREMENT,
    h2 TEXT NOT NULL,
    url_id INTEGER NOT NULL,
    FOREIGN KEY (url_id) REFERENCES internal_url (url_id) ON DELETE CASCADE
);

CREATE TABLE img_alt_tag (
    img_alt_tag_id INTEGER PRIMARY KEY AUTOINCREMENT,
    alt_text TEXT DEFAULT NULL,
    img_tag TEXT NOT NULL,
    url_id INTEGER NOT NULL,
    FOREIGN KEY (url_id) REFERENCES internal_url (url_id) ON DELETE CASCADE
);












