--
-- PostgreSQL database dump
--

-- Dumped from database version 14.15 (Ubuntu 14.15-0ubuntu0.22.04.1)
-- Dumped by pg_dump version 14.15 (Ubuntu 14.15-0ubuntu0.22.04.1)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: archon_clients; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.archon_clients (
    id integer NOT NULL,
    client_name character varying(100) NOT NULL,
    api_key character varying(255) NOT NULL,
    archon_version character varying(20) NOT NULL,
    last_synced timestamp with time zone DEFAULT now(),
    status character varying(10),
    "timestamp" timestamp with time zone NOT NULL,
    token character varying(50) NOT NULL,
    trade_type character varying(4),
    amount numeric(18,8) NOT NULL,
    price numeric(18,8) NOT NULL,
    profit_loss numeric(18,8),
    trade_status character varying(8),
    validated boolean DEFAULT false,
    created_at timestamp with time zone DEFAULT now(),
    CONSTRAINT archon_clients_status_check CHECK (((status)::text = ANY ((ARRAY['Active'::character varying, 'Inactive'::character varying])::text[]))),
    CONSTRAINT archon_clients_trade_status_check CHECK (((trade_status)::text = ANY ((ARRAY['Success'::character varying, 'Failure'::character varying])::text[]))),
    CONSTRAINT archon_clients_trade_type_check CHECK (((trade_type)::text = ANY ((ARRAY['Buy'::character varying, 'Sell'::character varying])::text[])))
);

ALTER TABLE public.archon_clients OWNER TO postgres;

--
-- Name: archon_clients_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.archon_clients_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER TABLE public.archon_clients_id_seq OWNER TO postgres;

--
-- Name: archon_clients_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.archon_clients_id_seq OWNED BY public.archon_clients.id;

--
-- Name: archon_tx; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.archon_tx (
    id integer NOT NULL,
    "timestamp" timestamp with time zone NOT NULL,
    token character varying(50) NOT NULL,
    trade_type character varying(4),
    amount numeric(18,8) NOT NULL,
    price numeric(18,8) NOT NULL,
    profit_loss numeric(18,8),
    status character varying(8),
    validated boolean DEFAULT false,
    created_at timestamp with time zone DEFAULT now(),
    CONSTRAINT archon_tx_status_check CHECK (((status)::text = ANY ((ARRAY['Success'::character varying, 'Failure'::character varying])::text[]))),
    CONSTRAINT archon_tx_trade_type_check CHECK (((trade_type)::text = ANY ((ARRAY['Buy'::character varying, 'Sell'::character varying])::text[])))
);

ALTER TABLE public.archon_tx OWNER TO postgres;

--
-- Name: archon_tx_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.archon_tx_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER TABLE public.archon_tx_id_seq OWNER TO postgres;

--
-- Name: archon_tx_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.archon_tx_id_seq OWNED BY public.archon_tx.id;

--
-- Name: candles; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.candles (
    id integer NOT NULL,
    token_pair character varying(50) NOT NULL,
    "timestamp" timestamp without time zone NOT NULL,
    open numeric(16,8) NOT NULL,
    high numeric(16,8) NOT NULL,
    low numeric(16,8) NOT NULL,
    close numeric(16,8) NOT NULL,
    ma_10 numeric(16,8),
    ma_50 numeric(16,8),
    doji_type character varying(20) DEFAULT 'None'::character varying NOT NULL,
    CONSTRAINT candles_pkey PRIMARY KEY (id),
    CONSTRAINT unique_timestamp_token_pair UNIQUE ("timestamp", token_pair)
);

ALTER TABLE public.candles OWNER TO postgres;

--
-- Name: candles_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.candles_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER TABLE public.candles_id_seq OWNER TO postgres;

--
-- Name: candles_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.candles_id_seq OWNED BY public.candles.id;

--
-- Name: learning_metrics; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.learning_metrics (
    id integer NOT NULL,
    "timestamp" timestamp without time zone NOT NULL,
    metric_type character varying(50) NOT NULL,
    value numeric(18,8) NOT NULL,
    source character varying(50) DEFAULT 'local'::character varying
);

ALTER TABLE public.learning_metrics OWNER TO postgres;

--
-- Name: learning_metrics_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.learning_metrics_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER TABLE public.learning_metrics_id_seq OWNER TO postgres;

--
-- Name: learning_metrics_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.learning_metrics_id_seq OWNED BY public.learning_metrics.id;

--
-- Name: validator; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.validator (
    transaction_hash text,
    wallet_address text NOT NULL,
    block_time timestamp without time zone NOT NULL,
    token_mint text,
    pre_balance double precision,
    post_balance double precision,
    trade_type text,
    transaction_emoji text,
    failed boolean DEFAULT false
);

ALTER TABLE public.validator OWNER TO postgres;

--
-- Name: whale_detector; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.whale_detector (
    whale_wallet text NOT NULL,
    detected_time timestamp without time zone NOT NULL,
    amount numeric,
    token text,
    trade_type text,
    classification text,
    archon_notes text,
    transaction_hash text NOT NULL
);

ALTER TABLE public.whale_detector OWNER TO postgres;

--
-- Name: archon_clients id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.archon_clients ALTER COLUMN id SET DEFAULT nextval('public.archon_clients_id_seq'::regclass);

--
-- Name: archon_tx id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.archon_tx ALTER COLUMN id SET DEFAULT nextval('public.archon_tx_id_seq'::regclass);

--
-- Name: candles id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.candles ALTER COLUMN id SET DEFAULT nextval('public.candles_id_seq'::regclass);

--
-- Name: learning_metrics id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.learning_metrics ALTER COLUMN id SET DEFAULT nextval('public.learning_metrics_id_seq'::regclass);

--
-- Name: archon_clients archon_clients_api_key_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.archon_clients
    ADD CONSTRAINT archon_clients_api_key_key UNIQUE (api_key);

--
-- Name: archon_clients archon_clients_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.archon_clients
    ADD CONSTRAINT archon_clients_pkey PRIMARY KEY (id);

--
-- Name: archon_tx archon_tx_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.archon_tx
    ADD CONSTRAINT archon_tx_pkey PRIMARY KEY (id);

--
-- Name: candles candles_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.candles
    ADD CONSTRAINT candles_pkey PRIMARY KEY (id);

--
-- Name: learning_metrics learning_metrics_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.learning_metrics
    ADD CONSTRAINT learning_metrics_pkey PRIMARY KEY (id);

--
-- Name: candles unique_timestamp_token_pair; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.candles
    ADD CONSTRAINT unique_timestamp_token_pair UNIQUE ("timestamp", token_pair);

--
-- Name: validator unique_transaction_hash; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.validator
    ADD CONSTRAINT unique_transaction_hash UNIQUE (transaction_hash);

--
-- Name: whale_detector whale_detector_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.whale_detector
    ADD CONSTRAINT whale_detector_pkey PRIMARY KEY (transaction_hash);

--
-- Name: idx_api_key; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_api_key ON public.archon_clients USING btree (api_key);

--
-- Name: idx_archon_tx_timestamp; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_archon_tx_timestamp ON public.archon_tx USING btree ("timestamp");

--
-- Name: idx_archon_tx_token; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_archon_tx_token ON public.archon_tx USING btree (token);

--
-- Name: idx_candles_pair; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_candles_pair ON public.candles USING btree (token_pair);

--
-- Name: idx_candles_timestamp; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_candles_timestamp ON public.candles USING btree ("timestamp");

--
-- Name: idx_classification; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_classification ON public.whale_detector USING btree (classification);

--
-- Name: idx_client_name; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_client_name ON public.archon_clients USING btree (client_name);

--
-- Name: idx_detected_time; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_detected_time ON public.whale_detector USING btree (detected_time);

--
-- Name: idx_last_synced; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_last_synced ON public.archon_clients USING btree (last_synced);

--
-- Name: idx_learning_metrics_metric_type; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_learning_metrics_metric_type ON public.learning_metrics USING btree (metric_type);

--
-- Name: idx_learning_metrics_timestamp; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_learning_metrics_timestamp ON public.learning_metrics USING btree ("timestamp");

--
-- Name: idx_token; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_token ON public.whale_detector USING btree (token);

--
-- Name: idx_token_timestamp; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_token_timestamp ON public.candles USING btree (token_pair, "timestamp");

--
-- Name: idx_trade_status; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_trade_status ON public.archon_clients USING btree (trade_status);

--
-- Name: idx_trade_timestamp; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_trade_timestamp ON public.archon_clients USING btree ("timestamp");

--
-- Name: idx_trade_token; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_trade_token ON public.archon_clients USING btree (token);

--
-- Name: idx_trade_type; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_trade_type ON public.archon_clients USING btree (trade_type);

--
-- Name: idx_whale_wallet; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_whale_wallet ON public.whale_detector USING btree (whale_wallet);

--
-- PostgreSQL database dump complete
--
