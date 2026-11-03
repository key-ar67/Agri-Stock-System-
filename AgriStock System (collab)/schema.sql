CREATE DATABASE IF NOT EXISTS agristock_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE agristock_db;

CREATE TABLE IF NOT EXISTS users (
  id INT AUTO_INCREMENT PRIMARY KEY,
  username VARCHAR(60) NOT NULL UNIQUE,
  password_hash VARCHAR(255) NOT NULL,
  full_name VARCHAR(120) NOT NULL,
  role ENUM('Admin','Staff') NOT NULL DEFAULT 'Staff',
  is_active TINYINT(1) NOT NULL DEFAULT 1,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS suppliers (
  id INT AUTO_INCREMENT PRIMARY KEY,
  supplier_name VARCHAR(150) NOT NULL,
  contact VARCHAR(100),
  address TEXT,
  email VARCHAR(120),
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS products (
  id INT AUTO_INCREMENT PRIMARY KEY,
  product_name VARCHAR(150) NOT NULL,
  category VARCHAR(100),
  unit VARCHAR(30) NOT NULL DEFAULT 'pcs',
  reorder_level INT NOT NULL DEFAULT 10,
  description TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS batches (
  id INT AUTO_INCREMENT PRIMARY KEY,
  batch_code VARCHAR(40) NOT NULL UNIQUE,
  product_id INT NOT NULL,
  supplier_id INT NULL,
  quantity_received INT NOT NULL,
  quantity_remaining INT NOT NULL,
  date_received DATE NOT NULL,
  manufacture_date DATE NULL,
  expiry_date DATE NOT NULL,
  created_by INT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (product_id) REFERENCES products(id),
  FOREIGN KEY (supplier_id) REFERENCES suppliers(id) ON DELETE SET NULL,
  FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE SET NULL,
  INDEX idx_batch_fefo(product_id, expiry_date, quantity_remaining)
);

CREATE TABLE IF NOT EXISTS stock_movements (
  id INT AUTO_INCREMENT PRIMARY KEY,
  movement_type ENUM('STOCK IN','STOCK OUT','ADJUSTMENT') NOT NULL,
  product_id INT NOT NULL,
  batch_id INT NULL,
  quantity INT NOT NULL,
  reference_no VARCHAR(80),
  notes TEXT,
  performed_by INT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (product_id) REFERENCES products(id),
  FOREIGN KEY (batch_id) REFERENCES batches(id) ON DELETE SET NULL,
  FOREIGN KEY (performed_by) REFERENCES users(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS knowledge_items (
  id INT AUTO_INCREMENT PRIMARY KEY,
  module_type ENUM('Seed Guide','Planting Calendar','Do and Don’t','Pest and Disease') NOT NULL,
  title VARCHAR(180) NOT NULL,
  crop VARCHAR(120),
  season VARCHAR(100),
  symptoms TEXT,
  content TEXT NOT NULL,
  prevention TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS audit_logs (
  id INT AUTO_INCREMENT PRIMARY KEY,
  user_id INT NULL,
  username VARCHAR(60) NOT NULL,
  action VARCHAR(120) NOT NULL,
  details TEXT,
  ip_address VARCHAR(60),
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
);
