/**
 * HomePage - Landing page for Re-ink application
 */
import React from 'react';
import { useNavigate } from 'react-router-dom';
import { FileText, Sparkles, Upload, CheckCircle, ArrowRight, Bot } from 'lucide-react';

export const HomePage: React.FC = () => {
  const navigate = useNavigate();

  return (
    <div className="home-page">
      {/* Hero Section */}
      <section className="hero-section">
        <div className="hero-content">
          <div className="hero-badge">
            <Sparkles size={16} />
            <span>AI-Powered Contract Management</span>
          </div>
          <h1 className="hero-title">
            <span className="gradient-text">Re-Ink</span>
            <br />
            Intelligent Reinsurance
          </h1>
          <p className="hero-description">
            Re-ink transforms complex reinsurance document processing with AI-powered extraction.
            Upload contracts, extract key fields automatically, and manage your reinsurance portfolio with ease.
          </p>
          <div className="hero-actions">
            <button
              onClick={() => navigate('/upload')}
              className="btn btn-primary btn-large"
            >
              <Upload size={20} />
              Upload Contract
              <ArrowRight size={20} />
            </button>
            <button
              onClick={() => navigate('/dashboard')}
              className="btn btn-secondary btn-large"
            >
              View Dashboard
            </button>
          </div>
        </div>

        <div className="hero-visual">
          <div className="visual-card card-1">
            <FileText size={32} />
            <span>Contract Documents</span>
          </div>
          <div className="visual-card card-2">
            <Sparkles size={32} />
            <span>AI Extraction</span>
          </div>
          <div className="visual-card card-3">
            <CheckCircle size={32} />
            <span>Structured Data</span>
          </div>
        </div>
      </section>

      {/* Features Section */}
      <section className="features-section">
        <h2 className="section-title">Powerful Features</h2>
        <p className="section-subtitle">
          Everything you need to manage reinsurance contracts efficiently
        </p>

        <div className="features-grid">
          <div className="feature-card">
            <div className="feature-icon">
              <Upload size={28} />
            </div>
            <h3>Document Upload</h3>
            <p>
              Upload complex reinsurance contract documents in PDF or DOCX format.
              Our system handles multi-page documents with ease.
            </p>
          </div>

          <div className="feature-card">
            <div className="feature-icon">
              <Sparkles size={28} />
            </div>
            <h3>AI-Powered Extraction</h3>
            <p>
              Powered by LandingAI's agentic document extraction, automatically extract
              contract terms, parties, dates, and financial details.
            </p>
          </div>

          <div className="feature-card">
            <div className="feature-icon">
              <FileText size={28} />
            </div>
            <h3>Contract Management</h3>
            <p>
              Organize and manage all your reinsurance contracts in one place.
              Track status, dates, and key terms effortlessly.
            </p>
          </div>

          <div className="feature-card">
            <div className="feature-icon">
              <CheckCircle size={28} />
            </div>
            <h3>Review & Approve</h3>
            <p>
              Review extracted data before it's saved. Edit any field to ensure
              accuracy and completeness.
            </p>
          </div>

          <div className="feature-card">
            <div className="feature-icon">
              <Bot size={28} />
            </div>
            <h3>Autonomous AI Agents</h3>
            <p>
              Embedded agents coordinate ingestion, extraction, and QA so your team
              can focus on decision-making instead of manual data wrangling.
            </p>
          </div>

          <div className="feature-card">
            <div className="feature-icon">
              <ArrowRight size={28} />
            </div>
            <h3>Smart Workflows</h3>
            <p>
              Streamlined workflows from document upload to data extraction to
              contract creation. Save hours of manual data entry.
            </p>
          </div>
        </div>
      </section>

      {/* How It Works Section */}
      <section className="how-it-works-section">
        <h2 className="section-title">How It Works</h2>
        <p className="section-subtitle">
          Get started in three simple steps
        </p>

        <div className="steps-container">
          <div className="step-card">
            <div className="step-number">1</div>
            <div className="step-content">
              <h3>Upload Document</h3>
              <p>
                Drag and drop your reinsurance contract document or browse to select.
                Supports PDF and DOCX formats.
              </p>
            </div>
          </div>

          <div className="step-divider">
            <ArrowRight size={24} />
          </div>

          <div className="step-card">
            <div className="step-number">2</div>
            <div className="step-content">
              <h3>AI Extraction</h3>
              <p>
                Our AI analyzes the document and extracts key information including
                contract details, parties, terms, and financial data.
              </p>
            </div>
          </div>

          <div className="step-divider">
            <ArrowRight size={24} />
          </div>

          <div className="step-card">
            <div className="step-number">3</div>
            <div className="step-content">
              <h3>Review & Save</h3>
              <p>
                Review the extracted data, make any necessary edits, and approve
                to create structured contract records.
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* CTA Section */}
      <section className="cta-section">
        <div className="cta-content">
          <h2>Ready to streamline your contract management?</h2>
          <p>Start extracting data from your reinsurance contracts today</p>
          <button
            onClick={() => navigate('/upload')}
            className="btn btn-primary btn-large"
          >
            <Upload size={20} />
            Get Started
          </button>
        </div>
      </section>
    </div>
  );
};
