create table kv_store (
    timestamp date not null,
    user_key text not null primary key,
    user_value text not null
);