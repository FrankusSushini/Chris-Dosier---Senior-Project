# Chris Dosier - Motion Detector Final
# Features include: automatic log/file creation


import cv2
import os
import datetime
import time
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
from picamera2 import Picamera2

# ===================== CONFIGURATION =====================
SAVE_FOLDER = os.path.join(os.path.expanduser("~"), "motion_captures")
MIN_AREA = 500                  # Motion sensitivity (pixels)
RESOLUTION = (640, 480)         # Camera resolution
SHOW_WINDOWS = False            # Set True for debugging
EMAIL_COOLDOWN = 300            # Seconds between emails

# Image management settings
MAX_SAVED_IMAGES = 100          # 0 = unlimited
IMAGE_RETENTION_DAYS = 7        # Auto-delete images older than X days
IMAGE_QUALITY = 85              # JPEG quality (1-100)

# Email settings (Gmail example)
EMAIL_SETTINGS = {
    "sender": "your_email@gmail.com",         #  Your full email
    "password": "your_app_password",         # 16-char Google App Password
    "receiver": "alerts@example.com",        #  Alert destination
    "smtp_server": "smtp.gmail.com",          # The email service you are using
    "port": 587,
    "subject": "Motion Detected!"
}

# ===================== MAIN SCRIPT =====================
class MotionDetector:
    def __init__(self):
        os.makedirs(SAVE_FOLDER, exist_ok=True)
        self.last_email_time = 0
        self.setup_camera()
        self.background_sub = cv2.createBackgroundSubtractorMOG2(
            history=500, varThreshold=25, detectShadows=False)
        
        # Initialize image counter
        self.update_image_count()

    def setup_camera(self):
        """Initialize camera with automatic fallback"""
        try:
            self.cam = Picamera2()
            config = self.cam.create_preview_configuration(main={"size": RESOLUTION})
            self.cam.configure(config)
            self.cam.start()
            time.sleep(2)  # Camera warm-up
            self.camera_type = "Pi"
            print(f"✅ Pi Camera initialized at {RESOLUTION[0]}x{RESOLUTION[1]}")
        except Exception as e:
            print(f"⚠️ Pi Camera failed: {str(e)}, trying USB...")
            self.cam = cv2.VideoCapture(0)
            if self.cam.isOpened():
                self.cam.set(cv2.CAP_PROP_FRAME_WIDTH, RESOLUTION[0])
                self.cam.set(cv2.CAP_PROP_FRAME_HEIGHT, RESOLUTION[1])
                self.camera_type = "USB"
                print(f"✅ USB Camera initialized at {RESOLUTION[0]}x{RESOLUTION[1]}")
            else:
                raise RuntimeError("❌ No camera detected")

    def update_image_count(self):
        """Count existing motion images"""
        self.saved_images_count = len([
            f for f in os.listdir(SAVE_FOLDER) 
            if f.startswith('motion_') and f.endswith('.jpg')
        ])

    def cleanup_old_images(self):
        """Delete images older than retention period"""
        now = time.time()
        deleted_count = 0
        
        for filename in os.listdir(SAVE_FOLDER):
            if filename.startswith('motion_') and filename.endswith('.jpg'):
                filepath = os.path.join(SAVE_FOLDER, filename)
                file_age = now - os.path.getmtime(filepath)
                if file_age > IMAGE_RETENTION_DAYS * 86400:  # Days to seconds
                    os.remove(filepath)
                    deleted_count += 1
        
        if deleted_count > 0:
            print(f"♻️ Deleted {deleted_count} old images")
            self.update_image_count()

    def enforce_image_limit(self):
        """Delete oldest images if over limit"""
        if MAX_SAVED_IMAGES <= 0:
            return
            
        images = sorted([
            os.path.join(SAVE_FOLDER, f) 
            for f in os.listdir(SAVE_FOLDER) 
            if f.startswith('motion_') and f.endswith('.jpg')
        ], key=os.path.getmtime)
        
        while len(images) >= MAX_SAVED_IMAGES:
            oldest = images.pop(0)
            os.remove(oldest)
            print(f"♻️ Deleted oldest image: {os.path.basename(oldest)}")
        
        self.update_image_count()

    def save_image(self, frame):
        """Save image with quality and limits enforcement"""
        self.cleanup_old_images()
        self.enforce_image_limit()
        
        if 0 < MAX_SAVED_IMAGES <= self.saved_images_count:
            print(f"⚠️ Image limit reached ({MAX_SAVED_IMAGES}), skipping save")
            return None
            
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = os.path.join(SAVE_FOLDER, f"motion_{timestamp}.jpg")
        
        # Save with adjustable quality
        cv2.imwrite(filename, frame, [int(cv2.IMWRITE_JPEG_QUALITY), IMAGE_QUALITY])
        self.saved_images_count += 1
        print(f"📸 Saved {os.path.basename(filename)} ({self.saved_images_count}/{MAX_SAVED_IMAGES})")
        return filename

    def get_frame(self):
        """Capture frame from active camera"""
        if self.camera_type == "Pi":
            frame = self.cam.capture_array()
            return cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
        else:
            ret, frame = self.cam.read()
            return frame if ret else None

    def detect_motion(self, frame):
        """Process frame for motion detection"""
        fgmask = self.background_sub.apply(frame)
        thresh = cv2.threshold(fgmask, 25, 255, cv2.THRESH_BINARY)[1]
        thresh = cv2.dilate(thresh, None, iterations=2)
        
        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        motion_detected = False
        
        for c in contours:
            if cv2.contourArea(c) > MIN_AREA:
                motion_detected = True
                x, y, w, h = cv2.boundingRect(c)
                cv2.rectangle(frame, (x, y), (x+w, y+h), (0, 255, 0), 2)
        
        return frame, motion_detected

    def send_email_alert(self, image_path):
        """Send email with motion capture attachment"""
        try:
            current_time = time.time()
            if current_time - self.last_email_time < EMAIL_COOLDOWN:
                print(f"⏳ Email cooldown active ({int(EMAIL_COOLDOWN - (current_time - self.last_email_time))}s remaining)")
                return

            print("✉️ Preparing email alert...")
            msg = MIMEMultipart()
            msg['From'] = EMAIL_SETTINGS["sender"]
            msg['To'] = EMAIL_SETTINGS["receiver"]
            msg['Subject'] = EMAIL_SETTINGS["subject"]
            
            body = f"""
            Motion Detected!
            - Time: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
            - Device: Raspberry Pi ({self.camera_type} Camera)
            - Current Images: {self.saved_images_count}/{MAX_SAVED_IMAGES}
            """
            msg.attach(MIMEText(body, 'plain'))
            
            with open(image_path, 'rb') as f:
                img = MIMEImage(f.read())
                img.add_header('Content-Disposition', 'attachment', filename="motion_alert.jpg")
                msg.attach(img)
            
            with smtplib.SMTP(EMAIL_SETTINGS["smtp_server"], EMAIL_SETTINGS["port"], timeout=10) as server:
                server.starttls()
                server.login(EMAIL_SETTINGS["sender"], EMAIL_SETTINGS["password"])
                server.send_message(msg)
            
            self.last_email_time = current_time
            print("✅ Email alert sent")
        
        except smtplib.SMTPAuthenticationError:
            print("❌ Email failed: Invalid credentials")
        except Exception as e:
            print(f"❌ Email failed: {str(e)}")

    def run(self):
        """Main detection loop"""
        print("\n=== MOTION DETECTOR ACTIVE ===")
        print(f"• Sensitivity: {MIN_AREA} px")
        print(f"• Resolution: {RESOLUTION[0]}x{RESOLUTION[1]}")
        print(f"• Image Limits: {MAX_SAVED_IMAGES} max, {IMAGE_RETENTION_DAYS} day retention")
        print(f"• Email Alerts: {'ON' if EMAIL_SETTINGS['sender'] else 'OFF'}")
        print("Press Q to quit (if windows enabled)\n")

        try:
            while True:
                frame = self.get_frame()
                if frame is None:
                    print("⚠️ Frame capture failed, retrying...")
                    time.sleep(1)
                    continue

                processed_frame, motion = self.detect_motion(frame)
                
                if motion:
                    filename = self.save_image(frame)
                    if filename:
                        self.send_email_alert(filename)

                if SHOW_WINDOWS:
                    cv2.imshow("Live Feed", processed_frame)
                    if cv2.waitKey(1) & 0xFF == ord('q'):
                        break
                else:
                    time.sleep(0.1)  # Reduce CPU usage in headless mode

        except KeyboardInterrupt:
            print("\nStopping detector...")
        finally:
            if hasattr(self, 'cam'):
                if self.camera_type == "Pi":
                    self.cam.stop()
                else:
                    self.cam.release()
            cv2.destroyAllWindows()
            print("System shutdown complete")

if __name__ == "__main__":
    detector = MotionDetector()
    detector.run()