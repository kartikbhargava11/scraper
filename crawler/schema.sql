DROP TABLE IF EXISTS user;
DROP TABLE IF EXISTS website;
DROP TABLE IF EXISTS internal_url;
DROP TABLE IF EXISTS crawl_job;
DROP TABLE IF EXISTS item;
DROP TABLE IF EXISTS specification;


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
    job_id INTEGER NOT NULL,
    max_depth INTEGER,
    max_pages INTEGER,
    FOREIGN KEY (job_id) REFERENCES crawl_job (job_id) ON DELETE CASCADE
);

CREATE TABLE internal_url (
    url_id INTEGER PRIMARY KEY AUTOINCREMENT,
    url_address TEXT NOT NULL,
    depth INTEGER DEFAULT NULL,
    job_id INTEGER NOT NULL,
    website_id INTEGER NOT NULL,
    error_message TEXT,
    status_code INTEGER,
    redirected_status_code INTEGER,
    page_description TEXT,
    llm_description TEXT,
    page_title TEXT,
    number_of_images INTEGER,
    number_of_internal_links INTEGER,
    keyword_relevance_score INTEGER,
    FOREIGN KEY (job_id) REFERENCES crawl_job (job_id) ON DELETE CASCADE,
    FOREIGN KEY (website_id) REFERENCES website (website_id)
);

CREATE TABLE item (
    item_id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL,
    url_id INTEGER,
    website_id INTEGER NOT NULL,
    name TEXT,
    description TEXT,
    price INTEGER,
    brand TEXT,
    product_code TEXT,
    availability TEXT,
    FOREIGN KEY (job_id) REFERENCES crawl_job (job_id) ON DELETE CASCADE,
    FOREIGN KEY (website_id) REFERENCES website (website_id) ON DELETE CASCADE,
    FOREIGN KEY (url_id) REFERENCES internal_url (url_id),
);

CREATE TABLE specification (
    specification_id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id INTEGER NOT NULL,
    category_name TEXT,
    category_value TEXT,
    FOREIGN KEY (item_id) REFERENCES item (item_id)
);
















