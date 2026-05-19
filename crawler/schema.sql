DROP TABLE IF EXISTS user;
DROP TABLE IF EXISTS website;
DROP TABLE IF EXISTS internal_url;
DROP TABLE IF EXISTS content;
DROP TABLE IF EXISTS tag;
DROP TABLE IF EXISTS status_type;
DROP TABLE IF EXISTS check_status;

CREATE TABLE user (
    user_id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password TEXT NOT NULL
);


CREATE TABLE website (
    website_id INTEGER PRIMARY KEY AUTOINCREMENT,
    website_url TEXT NOT NULL,
    created TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE internal_url (
    url_id INTEGER PRIMARY KEY AUTOINCREMENT,
    url_address TEXT NOT NULL,
    depth INTEGER NOT NULL,
    website_id INTEGER NOT NULL,
    created TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (website_id) REFERENCES website (website_id)
);

CREATE TABLE content (
    content_id INTEGER PRIMARY KEY AUTOINCREMENT,
    html TEXT NOT NULL,
    url_id INTEGER NOT NULL,
    crawl_status_code INTEGER NOT NULL,
    created TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (url_id) REFERENCES internal_url (url_id)
);

CREATE TABLE tag (
    tag_id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    h1 TEXT NOT NULL,
    url_id INTEGER NOT NULL,
    created TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (url_id) REFERENCES internal_url (url_id)
);

CREATE TABLE status_type (
    status_type_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL
);

INSERT INTO status_type (name)
VALUES ('PENDING'),
    ('COMPLETED'),
    ('FAILURE'),
    ('SUCCESS'),
    ('STARTED');

CREATE TABLE check_status (
    status_id INTEGER PRIMARY KEY AUTOINCREMENT,
    status_type_id INTEGER NOT NULL,
    website_id INTEGER NULL,
    url_id INTEGER NULL,
    task_id INTEGER NOT NULL,
    FOREIGN KEY (status_type_id) REFERENCES status_type(status_type_id),
    FOREIGN KEY (website_id) REFERENCES website(website_id),
    FOREIGN KEY (url_id) REFERENCES internal_url(url_id),

    -- it ensures a row always belong to either website_id or url_id
    CHECK (website_id IS NOT NULL OR url_id IS NOT NULL)
);










