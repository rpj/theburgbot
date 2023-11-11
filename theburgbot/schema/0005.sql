create table events (
    timestamp date not null,
    snowflake text not null,
    json_digest text not null,
    json text not null
);