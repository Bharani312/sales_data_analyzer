from flask import Flask, render_template, request, redirect, url_for, flash
import mysql.connector
from mysql.connector import Error, pooling
import time
import atexit

app = Flask(__name__)
app.secret_key = 'your_secret_key_here'

# Database Configuration
DB_CONFIG = {
    'host': 'localhost',
    'database': 'analyzer',
    'user': 'root',
    'password': '',
    'pool_name': 'sales_pool',
    'pool_size': 5,
    'autocommit': True
}

class Database:
    _connection_pool = None
    
    @classmethod
    def initialize_pool(cls):
        try:
            cls._connection_pool = pooling.MySQLConnectionPool(**DB_CONFIG)
            print("Connection pool created successfully")
        except Error as e:
            print(f"Error creating connection pool: {e}")
            cls._connection_pool = None

    @classmethod
    def get_connection(cls):
        if not cls._connection_pool:
            cls.initialize_pool()
        
        attempts = 0
        while attempts < 3:
            try:
                connection = cls._connection_pool.get_connection()
                if connection.is_connected():
                    print("Got connection from pool")
                    return connection
            except Error as e:
                print(f"Connection attempt {attempts + 1} failed: {e}")
                time.sleep(1)
                attempts += 1
                if attempts == 3:
                    print("Max connection attempts reached")
                    raise

    @classmethod
    def execute_query(cls, query, params=None, fetch=False):
        connection = None
        cursor = None
        try:
            connection = cls.get_connection()
            cursor = connection.cursor(dictionary=True)
            cursor.execute(query, params or ())
            
            if fetch:
                result = cursor.fetchall()
            else:
                connection.commit()
                result = cursor.lastrowid
            
            return result
        except Error as e:
            print(f"Database error: {e}")
            return None
        finally:
            if cursor:
                cursor.close()
            if connection:
                connection.close()

# Initialize connection pool when app starts
Database.initialize_pool()

# Test connection immediately
try:
    test_conn = Database.get_connection()
    if test_conn and test_conn.is_connected():
        print("Successfully connected to MySQL!")
        test_conn.close()
    else:
        print("Failed to connect to MySQL")
except Exception as e:
    print(f"Initial connection test failed: {e}")

@app.route('/')
def dashboard():
    try:
        # Get total sales
        total_sales_data = Database.execute_query(
            "SELECT SUM(quantity_sold * sale_price) as total FROM Sales_Transactions",
            fetch=True
        )
        total_sales = total_sales_data[0]['total'] if total_sales_data and total_sales_data[0]['total'] else 0
        
        # Get sales by product
        sales_by_product = Database.execute_query(
            """SELECT p.product_name, SUM(s.quantity_sold) as total_quantity, 
               SUM(s.quantity_sold * s.sale_price) as total_sales
               FROM Sales_Transactions s
               JOIN Products p ON s.product_id = p.product_id
               GROUP BY p.product_name""",
            fetch=True
        ) or []
        
        # Get recent sales
        recent_sales = Database.execute_query(
            """SELECT s.sale_id, p.product_name, s.quantity_sold, s.sale_price, s.sale_date
               FROM Sales_Transactions s
               JOIN Products p ON s.product_id = p.product_id
               ORDER BY s.sale_date DESC LIMIT 5""",
            fetch=True
        ) or []
        
        return render_template('dashboard.html', 
                            total_sales=total_sales,
                            sales_by_product=sales_by_product,
                            recent_sales=recent_sales)
    except Exception as e:
        flash(f'Error loading dashboard: {str(e)}', 'danger')
        return render_template('dashboard.html', 
                            total_sales=0,
                            sales_by_product=[],
                            recent_sales=[])

@app.route('/products')
def products():
    try:
        product_list = Database.execute_query(
            "SELECT * FROM Products ORDER BY date_added DESC",
            fetch=True
        ) or []
        return render_template('products.html', products=product_list)
    except Exception as e:
        flash(f'Error loading products: {str(e)}', 'danger')
        return render_template('products.html', products=[])

@app.route('/add_product', methods=['GET', 'POST'])
def add_product():
    if request.method == 'POST':
        try:
            product_name = request.form['product_name']
            category = request.form['category']
            unit_price = float(request.form['unit_price'])
            stock_quantity = int(request.form['stock_quantity'])
            
            Database.execute_query(
                """INSERT INTO Products (product_name, category, unit_price, stock_quantity)
                   VALUES (%s, %s, %s, %s)""",
                (product_name, category, unit_price, stock_quantity)
            )
            flash('Product added successfully!', 'success')
            return redirect(url_for('products'))
        except Exception as e:
            flash(f'Error adding product: {str(e)}', 'danger')
    
    return render_template('add_product.html')

@app.route('/sales')
def sales():
    try:
        sales_data = Database.execute_query(
            """SELECT s.sale_id, p.product_name, s.quantity_sold, 
               s.sale_price, (s.quantity_sold * s.sale_price) as total,
               s.sale_date
               FROM Sales_Transactions s
               JOIN Products p ON s.product_id = p.product_id
               ORDER BY s.sale_date DESC""",
            fetch=True
        ) or []
        
        total_sales_data = Database.execute_query(
            "SELECT SUM(quantity_sold * sale_price) as total FROM Sales_Transactions",
            fetch=True
        )
        total_sales = total_sales_data[0]['total'] if total_sales_data and total_sales_data[0]['total'] else 0
        
        return render_template('sales.html', sales=sales_data, total_sales=total_sales)
    except Exception as e:
        flash(f'Error loading sales: {str(e)}', 'danger')
        return render_template('sales.html', sales=[], total_sales=0)

@app.route('/add_sale', methods=['GET', 'POST'])
def add_sale():
    if request.method == 'POST':
        try:
            product_id = int(request.form['product_id'])
            quantity_sold = int(request.form['quantity_sold'])
            sale_price = float(request.form['sale_price'])
            
            # Check product stock
            product = Database.execute_query(
                "SELECT stock_quantity FROM Products WHERE product_id = %s",
                (product_id,), fetch=True
            )
            
            if not product:
                flash('Product not found!', 'danger')
                return redirect(url_for('add_sale'))
            
            if product[0]['stock_quantity'] < quantity_sold:
                flash(f'Not enough stock! Only {product[0]["stock_quantity"]} available.', 'danger')
                return redirect(url_for('add_sale'))
            
            # Add sale
            Database.execute_query(
                """INSERT INTO Sales_Transactions (product_id, quantity_sold, sale_price)
                   VALUES (%s, %s, %s)""",
                (product_id, quantity_sold, sale_price)
            )
            
            # Update stock
            Database.execute_query(
                "UPDATE Products SET stock_quantity = stock_quantity - %s WHERE product_id = %s",
                (quantity_sold, product_id)
            )
            
            flash('Sale recorded successfully!', 'success')
            return redirect(url_for('sales'))
        except Exception as e:
            flash(f'Error recording sale: {str(e)}', 'danger')
    
    # Get product list for dropdown
    products = Database.execute_query(
        "SELECT product_id, product_name FROM Products ORDER BY product_name",
        fetch=True
    ) or []
    return render_template('add_sale.html', products=products)

# Optional: Graceful shutdown
@atexit.register
def close_connection_pool():
    if Database._connection_pool:
        print("Shutting down connection pool...")
        Database._connection_pool._remove_connections()

if __name__ == '__main__':
    app.run(debug=True)
