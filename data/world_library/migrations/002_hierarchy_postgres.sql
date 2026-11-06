ALTER TABLE wl_links DROP CONSTRAINT wl_links_relation_check;
ALTER TABLE wl_links ADD CONSTRAINT wl_links_relation_check CHECK(relation IN ('component','input','output','spell','combines','species','starting_inventory','parent','child'));
CREATE TABLE wl_schema_revisions(id TEXT NOT NULL, digest TEXT NOT NULL, schema_json JSONB NOT NULL, PRIMARY KEY(id,digest));
