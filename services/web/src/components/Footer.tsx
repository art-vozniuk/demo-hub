const Footer = () => {
  return (
    <footer className="border-t border-border py-6">
      <div className="container mx-auto px-6 text-center">
        <p className="text-sm text-muted-foreground">
          © {new Date().getFullYear()} AI Showcase. All rights reserved.
        </p>
      </div>
    </footer>
  );
};

export default Footer;
