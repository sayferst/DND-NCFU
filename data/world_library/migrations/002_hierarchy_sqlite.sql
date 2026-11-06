CREATE TABLE wl_links_v2(id TEXT NOT NULL, revision INTEGER NOT NULL, ordinal INTEGER NOT NULL, relation TEXT NOT NULL CHECK(relation IN ('component','input','output','spell','combines','species','starting_inventory','parent','child')), target_id TEXT NOT NULL, target_revision INTEGER NOT NULL, quantity INTEGER NOT NULL CHECK(quantity>0), role TEXT NOT NULL, PRIMARY KEY(id,revision,ordinal), FOREIGN KEY(id,revision) REFERENCES wl_versions(id,revision), FOREIGN KEY(target_id,target_revision) REFERENCES wl_versions(id,revision));
INSERT INTO wl_links_v2 SELECT * FROM wl_links;
DROP TABLE wl_links;
ALTER TABLE wl_links_v2 RENAME TO wl_links;
CREATE INDEX wl_component_target ON wl_links(target_id,target_revision);
CREATE TABLE wl_schema_revisions(id TEXT NOT NULL, digest TEXT NOT NULL, schema_json TEXT NOT NULL, PRIMARY KEY(id,digest));
