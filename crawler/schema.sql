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
    FOREIGN KEY (website_id) REFERENCES website (website_id) ON DELETE CASCADE
);

CREATE TABLE markup (
    markup_id INTEGER PRIMARY KEY AUTOINCREMENT,
    html TEXT NOT NULL,
    url_id INTEGER NOT NULL,
    website_id INTEGER NOT NULL,
    crawl_status_code INTEGER NOT NULL,
    total_img_tags INTEGER NOT NULL,
    created TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (url_id) REFERENCES internal_url (url_id)
    FOREIGN KEY (website_id) REFERENCES internal_url (website_id) ON DELETE CASCADE
);

CREATE TABLE title_tag (
    title_tag_id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    url_id INTEGER NOT NULL,
    created TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (url_id) REFERENCES internal_url (url_id) ON DELETE CASCADE
);

CREATE TABLE h1_tag (
    h1_tag_id INTEGER PRIMARY KEY AUTOINCREMENT,
    h1 TEXT NOT NULL,
    url_id INTEGER NOT NULL,
    created TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (url_id) REFERENCES internal_url (url_id) ON DELETE CASCADE
);

CREATE TABLE h2_tag (
    h2_tag_id INTEGER PRIMARY KEY AUTOINCREMENT,
    h2 TEXT NOT NULL,
    url_id INTEGER NOT NULL,
    created TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (url_id) REFERENCES internal_url (url_id) ON DELETE CASCADE
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
    FOREIGN KEY (website_id) REFERENCES website(website_id) ON DELETE CASCADE,
    FOREIGN KEY (url_id) REFERENCES internal_url(url_id),

    -- it ensures a row always belong to either website_id or url_id
    CHECK (website_id IS NOT NULL OR url_id IS NOT NULL)
);










